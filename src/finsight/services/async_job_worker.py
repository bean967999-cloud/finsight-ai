"""Claim one queued job, execute it outside the database transaction, then acknowledge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from finsight.domain.async_job import (
    AsyncJobStatus,
    ChunkIndexTask,
    DocumentParseTask,
    TaskPayload,
    assert_job_transition,
)
from finsight.infrastructure.database.models import AsyncJob
from finsight.services.async_job_queue import AsyncJobQueue, QueueMessage
from finsight.services.async_job_submission import AsyncJobSubmissionService
from finsight.services.document_chunk_indexing import DocumentChunkIndexingService
from finsight.services.document_parsing import DocumentParsingService

SessionProvider = Callable[[], Session]


class AsyncJobHandler(Protocol):
    def execute(self, task: TaskPayload) -> str: ...


class DocumentTaskHandler:
    def __init__(
        self,
        parsing: DocumentParsingService,
        indexing: DocumentChunkIndexingService,
    ) -> None:
        self._parsing = parsing
        self._indexing = indexing

    def execute(self, task: TaskPayload) -> str:
        if isinstance(task, DocumentParseTask):
            parse_job_id = self._parsing.parse_document(task.document_id)
            return f"document_parse_job:{parse_job_id}"
        if isinstance(task, ChunkIndexTask):
            result = self._indexing.index_parse_job(
                task.parse_job_id,
                chunk_version=task.chunk_version,
            )
            return f"chunk_index:{result.parse_job_id}:v{result.chunk_version}"
        raise ValueError("unsupported task kind")


class AsyncJobMessageError(ValueError):
    """A message does not match a durable job and must not run it."""


@dataclass(frozen=True, slots=True)
class WorkOutcome:
    job_id: int
    status: AsyncJobStatus
    executed: bool


class AsyncJobWorker:
    def __init__(
        self,
        sessions: SessionProvider,
        queue: AsyncJobQueue,
        handler: AsyncJobHandler,
    ) -> None:
        self._sessions = sessions
        self._queue = queue
        self._handler = handler

    def process_one(
        self, consumer: str, *, block_ms: int = 1000, recovery_idle_ms: int = 900_000
    ) -> WorkOutcome | None:
        message = self._queue.reclaim_stale(consumer, min_idle_ms=recovery_idle_ms)
        recovered = message is not None
        if message is None:
            message = self._queue.read_new(consumer, block_ms=block_ms)
        if message is None:
            return None
        recovery = self._recover(message, recovery_idle_ms) if recovered else False
        if recovery is None:
            return WorkOutcome(message.job_id, AsyncJobStatus.RUNNING, executed=False)
        if recovery:
            self._queue.acknowledge(message.message_id)
            with self._sessions() as session:
                current = session.get(AsyncJob, message.job_id)
                if current is None:
                    raise AsyncJobMessageError("recovered job disappeared")
                return WorkOutcome(message.job_id, current.status, executed=False)
        task = self._claim(message)
        if task is None:
            self._queue.acknowledge(message.message_id)
            with self._sessions() as session:
                current = session.get(AsyncJob, message.job_id)
                if current is None:
                    raise AsyncJobMessageError("job disappeared after duplicate message")
                return WorkOutcome(message.job_id, current.status, executed=False)
        try:
            result_ref = self._handler.execute(task)
            if not result_ref or len(result_ref) > 200:
                raise ValueError("handler returned an invalid result reference")
        except Exception as exc:  # noqa: BLE001 - isolate and record task failures
            status = self._record_failure(message.job_id, type(exc).__name__)
            outcome = WorkOutcome(message.job_id, status, executed=True)
        else:
            self._finish(message.job_id, AsyncJobStatus.SUCCEEDED, result_ref=result_ref)
            outcome = WorkOutcome(message.job_id, AsyncJobStatus.SUCCEEDED, executed=True)
        self._queue.acknowledge(message.message_id)
        return outcome

    def _claim(self, message: QueueMessage) -> TaskPayload | None:
        with self._sessions() as session, session.begin():
            job = session.get(AsyncJob, message.job_id, with_for_update=True)
            if job is None or job.request_sha256 != message.request_sha256:
                raise AsyncJobMessageError("queue message does not match a durable job")
            snapshot = AsyncJobSubmissionService._snapshot(job)
            if job.status not in {AsyncJobStatus.PENDING, AsyncJobStatus.QUEUED}:
                return None
            if job.status == AsyncJobStatus.PENDING:
                # Publish may have succeeded while the dispatcher's database commit failed.
                assert_job_transition(snapshot, AsyncJobStatus.QUEUED)
                job.status = AsyncJobStatus.QUEUED
                snapshot = snapshot.model_copy(update={"status": AsyncJobStatus.QUEUED})
            assert_job_transition(snapshot, AsyncJobStatus.RUNNING)
            job.status = AsyncJobStatus.RUNNING
            job.attempt_count += 1
            return snapshot.task

    def _finish(
        self,
        job_id: int,
        target: AsyncJobStatus,
        *,
        result_ref: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._sessions() as session, session.begin():
            job = session.get(AsyncJob, job_id, with_for_update=True)
            if job is None:
                raise AsyncJobMessageError("job disappeared before completion")
            assert_job_transition(AsyncJobSubmissionService._snapshot(job), target)
            job.status = target
            job.result_ref = result_ref
            job.error_code = error_code[:100] if error_code else None

    def _record_failure(self, job_id: int, error_code: str) -> AsyncJobStatus:
        with self._sessions() as session, session.begin():
            job = session.get(AsyncJob, job_id, with_for_update=True)
            if job is None:
                raise AsyncJobMessageError("job disappeared before failure recording")
            target = (
                AsyncJobStatus.RETRY_WAIT
                if job.attempt_count < job.max_attempts
                else AsyncJobStatus.FAILED
            )
            assert_job_transition(AsyncJobSubmissionService._snapshot(job), target)
            job.status = target
            job.error_code = error_code[:100]
            job.next_retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(60 * 2 ** (job.attempt_count - 1), 3600))
                if target == AsyncJobStatus.RETRY_WAIT
                else None
            )
            return target

    def _recover(self, message: QueueMessage, min_idle_ms: int) -> bool | None:
        """Finalize a stale running attempt; queued messages remain executable."""
        with self._sessions() as session, session.begin():
            job = session.get(AsyncJob, message.job_id, with_for_update=True)
            if job is None or job.request_sha256 != message.request_sha256:
                raise AsyncJobMessageError("reclaimed message does not match a durable job")
            if job.status != AsyncJobStatus.RUNNING:
                return job.status not in {AsyncJobStatus.PENDING, AsyncJobStatus.QUEUED}
            updated = job.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if updated > datetime.now(UTC) - timedelta(milliseconds=min_idle_ms):
                return None
            target = (
                AsyncJobStatus.RETRY_WAIT
                if job.attempt_count < job.max_attempts
                else AsyncJobStatus.FAILED
            )
            assert_job_transition(AsyncJobSubmissionService._snapshot(job), target)
            job.status = target
            job.error_code = "WorkerLost"
            job.next_retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(60 * 2 ** (job.attempt_count - 1), 3600))
                if target == AsyncJobStatus.RETRY_WAIT
                else None
            )
            return True
