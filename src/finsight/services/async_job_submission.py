"""Atomically persist one logical job or replay its identical submission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finsight.domain.async_job import (
    AsyncJobSnapshot,
    AsyncJobSubmission,
    ChunkIndexTask,
    DocumentParseTask,
)
from finsight.domain.document_data import DocumentParseStatus
from finsight.infrastructure.database.models import (
    AsyncJob,
    Document,
    DocumentParseJob,
    KnowledgeBaseDocument,
)

SessionProvider = Callable[[], Session]


class AsyncJobConflict(ValueError):
    """An idempotency key has already been used for another request."""


class AsyncJobTargetError(ValueError):
    """The requested document or parse result is not ready for this task."""


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    job: AsyncJobSnapshot
    replayed: bool


class AsyncJobSubmissionService:
    def __init__(self, session_provider: SessionProvider) -> None:
        self._sessions = session_provider

    def submit(self, request: AsyncJobSubmission) -> SubmissionResult:
        """The unique database key resolves concurrent duplicates, not a read-before-write lock."""
        try:
            with self._sessions() as session, session.begin():
                existing = session.scalar(
                    select(AsyncJob).where(
                        AsyncJob.idempotency_key == request.idempotency_key,
                    )
                )
                if existing is not None:
                    return self._replay(existing, request)
                self._ensure_target(session, request)
                job = AsyncJob(
                    idempotency_key=request.idempotency_key,
                    knowledge_base_id=request.knowledge_base_id,
                    request_sha256=request.request_sha256,
                    task_kind=request.task.kind,
                    task_payload=request.task.model_dump(mode="json"),
                    max_attempts=request.max_attempts,
                )
                session.add(job)
                session.flush()
                return SubmissionResult(self._snapshot(job), replayed=False)
        except IntegrityError:
            # Another transaction may have inserted the same key after our initial read.
            with self._sessions() as session:
                existing = session.scalar(
                    select(AsyncJob).where(
                        AsyncJob.idempotency_key == request.idempotency_key,
                    )
                )
                if existing is None:
                    raise
                return self._replay(existing, request)

    @staticmethod
    def _ensure_target(session: Session, request: AsyncJobSubmission) -> None:
        task = request.task
        if isinstance(task, DocumentParseTask):
            if session.get(Document, task.document_id) is None:
                raise AsyncJobTargetError("document does not exist")
            document_id = task.document_id
        elif isinstance(task, ChunkIndexTask):
            parse_job = session.get(DocumentParseJob, task.parse_job_id)
            if parse_job is None or parse_job.status != DocumentParseStatus.SUCCEEDED:
                raise AsyncJobTargetError("successful parse job is required for indexing")
            document_id = parse_job.document_id
        else:
            raise AsyncJobTargetError("unsupported document task")
        if request.knowledge_base_id is not None and session.get(
            KnowledgeBaseDocument, (request.knowledge_base_id, document_id)
        ) is None:
            raise AsyncJobTargetError("document is outside the selected knowledge base")

    @staticmethod
    def _replay(existing: AsyncJob, request: AsyncJobSubmission) -> SubmissionResult:
        if existing.request_sha256 != request.request_sha256:
            raise AsyncJobConflict("idempotency key belongs to a different request")
        return SubmissionResult(AsyncJobSubmissionService._snapshot(existing), replayed=True)

    @staticmethod
    def _snapshot(job: AsyncJob) -> AsyncJobSnapshot:

        request = AsyncJobSubmission.model_validate(
            {
                "idempotency_key": job.idempotency_key,
                "knowledge_base_id": job.knowledge_base_id,
                "task": job.task_payload,
                "max_attempts": job.max_attempts,
            }
        )
        return AsyncJobSnapshot(
            job_id=job.id,
            idempotency_key=job.idempotency_key,
            knowledge_base_id=job.knowledge_base_id,
            request_sha256=job.request_sha256,
            task=request.task,
            status=job.status,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            result_ref=job.result_ref,
            error_code=job.error_code,
            next_retry_at=(
                job.next_retry_at.replace(tzinfo=UTC)
                if job.next_retry_at is not None and job.next_retry_at.tzinfo is None
                else job.next_retry_at
            ),
        )
