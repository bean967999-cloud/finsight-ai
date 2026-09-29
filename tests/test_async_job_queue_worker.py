from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.async_job import AsyncJobStatus, AsyncJobSubmission, DocumentParseTask
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AsyncJob, Document
from finsight.services.async_job_dispatcher import AsyncJobDispatcher
from finsight.services.async_job_queue import QueueMessage
from finsight.services.async_job_submission import AsyncJobSubmissionService
from finsight.services.async_job_worker import AsyncJobMessageError, AsyncJobWorker


class FakeQueue:
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.acked: list[str] = []
        self.publish_error = False
        self.stale: list[QueueMessage] = []

    def publish(self, job_id: int, request_sha256: str) -> str:
        if self.publish_error:
            raise ConnectionError("queue unavailable")
        message_id = f"{len(self.messages) + 1}-0"
        self.messages.append(QueueMessage(message_id, job_id, request_sha256))
        return message_id

    def read_new(self, consumer: str, *, block_ms: int = 1000) -> QueueMessage | None:
        return self.messages.pop(0) if self.messages else None

    def acknowledge(self, message_id: str) -> None:
        self.acked.append(message_id)

    def reclaim_stale(self, consumer: str, *, min_idle_ms: int) -> QueueMessage | None:
        return self.stale.pop(0) if self.stale else None


class FakeHandler:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.calls = 0

    def execute(self, task) -> str:
        self.calls += 1
        if self.fails:
            raise OSError("parser temporarily unavailable")
        return "document_parse_job:42"


@pytest.fixture
def environment():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        document = Document(
            title="2024 report",
            document_type=DocumentType.ANNUAL_REPORT,
            company_code="TEST",
            report_year=2024,
            report_period_end=date(2024, 12, 31),
            object_key="documents/report.pdf",
            content_sha256="a" * 64,
            file_size_bytes=20,
        )
        session.add(document)
        session.flush()
        document_id = document.id
    request = AsyncJobSubmission(
        idempotency_key="parse-one",
        task=DocumentParseTask(document_id=document_id),
    )
    job_id = AsyncJobSubmissionService(sessions).submit(request).job.job_id
    yield sessions, request, job_id
    engine.dispose()


def test_dispatch_then_worker_success_commits_before_ack(environment) -> None:
    sessions, request, job_id = environment
    queue = FakeQueue()
    handler = FakeHandler()
    assert AsyncJobDispatcher(sessions, queue).dispatch_pending() == (job_id,)
    with sessions() as session:
        assert session.get(AsyncJob, job_id).status == AsyncJobStatus.QUEUED
    outcome = AsyncJobWorker(sessions, queue, handler).process_one("worker-1")
    assert outcome is not None and outcome.status == AsyncJobStatus.SUCCEEDED
    assert handler.calls == 1
    assert queue.acked == ["1-0"]
    with sessions() as session:
        stored = session.get(AsyncJob, job_id)
        assert stored is not None
        assert stored.attempt_count == 1
        assert stored.result_ref == "document_parse_job:42"
        assert stored.request_sha256 == request.request_sha256


def test_failed_publish_keeps_pending_job_for_later_dispatch(environment) -> None:
    sessions, _, job_id = environment
    queue = FakeQueue()
    queue.publish_error = True
    with pytest.raises(ConnectionError, match="unavailable"):
        AsyncJobDispatcher(sessions, queue).dispatch_pending()
    with sessions() as session:
        assert session.get(AsyncJob, job_id).status == AsyncJobStatus.PENDING
    queue.publish_error = False
    assert AsyncJobDispatcher(sessions, queue).dispatch_pending() == (job_id,)


def test_publish_commit_gap_and_duplicate_message_do_not_reexecute(environment) -> None:
    sessions, request, job_id = environment
    queue = FakeQueue()
    queue.publish(job_id, request.request_sha256)
    worker = AsyncJobWorker(sessions, queue, FakeHandler())
    first = worker.process_one("worker-1")
    assert first is not None and first.status == AsyncJobStatus.SUCCEEDED
    queue.publish(job_id, request.request_sha256)
    second = worker.process_one("worker-1")
    assert second is not None and not second.executed
    assert queue.acked == ["1-0", "1-0"]
    with sessions() as session:
        assert session.get(AsyncJob, job_id).attempt_count == 1


def test_handler_failure_waits_then_retries_before_final_failure(environment) -> None:
    sessions, _, job_id = environment
    queue = FakeQueue()
    AsyncJobDispatcher(sessions, queue).dispatch_pending()
    handler = FakeHandler(fails=True)
    worker = AsyncJobWorker(sessions, queue, handler)
    outcome = worker.process_one("worker-1")
    assert outcome is not None and outcome.status == AsyncJobStatus.RETRY_WAIT
    assert queue.acked == ["1-0"]
    with sessions() as session:
        stored = session.get(AsyncJob, job_id)
        assert stored is not None and stored.error_code == "OSError"
        assert stored.next_retry_at is not None
        due = stored.next_retry_at
    dispatcher = AsyncJobDispatcher(sessions, queue)
    assert dispatcher.dispatch_pending(now=due - timedelta(seconds=1)) == ()
    assert dispatcher.dispatch_pending(now=due) == (job_id,)
    assert worker.process_one("worker-1").status == AsyncJobStatus.RETRY_WAIT
    with sessions() as session:
        due = session.get(AsyncJob, job_id).next_retry_at
    assert dispatcher.dispatch_pending(now=due) == (job_id,)
    assert worker.process_one("worker-1").status == AsyncJobStatus.FAILED
    with sessions() as session:
        stored = session.get(AsyncJob, job_id)
        assert stored.attempt_count == 3
        assert stored.next_retry_at is None


def test_reclaimed_running_job_becomes_retry_wait(environment) -> None:
    sessions, _, job_id = environment
    queue = FakeQueue()
    AsyncJobDispatcher(sessions, queue).dispatch_pending()
    message = queue.read_new("lost-worker")
    assert message is not None
    worker = AsyncJobWorker(sessions, queue, FakeHandler())
    worker._claim(message)
    with sessions() as session, session.begin():
        job = session.get(AsyncJob, job_id)
        job.updated_at = datetime.now(UTC) - timedelta(minutes=20)
    queue.stale.append(message)
    outcome = worker.process_one("replacement", recovery_idle_ms=900_000)
    assert outcome is not None and outcome.status == AsyncJobStatus.RETRY_WAIT
    assert not outcome.executed
    assert queue.acked == [message.message_id]
    with sessions() as session:
        assert session.get(AsyncJob, job_id).error_code == "WorkerLost"


def test_wrong_digest_is_not_executed_or_acknowledged(environment) -> None:
    sessions, _, job_id = environment
    queue = FakeQueue()
    queue.publish(job_id, "b" * 64)
    handler = FakeHandler()
    with pytest.raises(AsyncJobMessageError, match="does not match"):
        AsyncJobWorker(sessions, queue, handler).process_one("worker-1")
    assert handler.calls == 0
    assert queue.acked == []
