from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.async_job import (
    AsyncJobStatus,
    AsyncJobSubmission,
    ChunkIndexTask,
    DocumentParseTask,
)
from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AsyncJob, Document, DocumentParseJob
from finsight.services.async_job_submission import (
    AsyncJobConflict,
    AsyncJobSubmissionService,
    AsyncJobTargetError,
)


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    yield factory
    engine.dispose()


def add_document(sessions, *, digest: str = "a" * 64) -> int:
    with sessions() as session, session.begin():
        document = Document(
            title="2024 年度报告",
            document_type=DocumentType.ANNUAL_REPORT,
            company_code="TEST",
            report_year=2024,
            report_period_end=date(2024, 12, 31),
            object_key=f"documents/{digest}.pdf",
            content_sha256=digest,
            file_size_bytes=20,
        )
        session.add(document)
        session.flush()
        return document.id


def request(document_id: int, *, key: str = "parse-report", max_attempts: int = 3):
    return AsyncJobSubmission(
        idempotency_key=key,
        task=DocumentParseTask(document_id=document_id),
        max_attempts=max_attempts,
    )


def test_submit_is_durable_and_replay_uses_same_job(sessions) -> None:
    document_id = add_document(sessions)
    first = AsyncJobSubmissionService(sessions).submit(request(document_id))
    second = AsyncJobSubmissionService(sessions).submit(request(document_id))
    assert not first.replayed
    assert second.replayed
    assert second.job.job_id == first.job.job_id
    assert first.job.status == AsyncJobStatus.PENDING
    assert first.job.attempt_count == 0
    with sessions() as session:
        stored = session.get(AsyncJob, first.job.job_id)
        assert stored is not None
        assert stored.request_sha256 == request(document_id).request_sha256
        assert stored.task_payload["document_id"] == document_id
        assert session.scalar(select(func.count()).select_from(AsyncJob)) == 1


def test_same_key_different_document_or_retry_policy_conflicts(sessions) -> None:
    first_id = add_document(sessions)
    second_id = add_document(sessions, digest="b" * 64)
    service = AsyncJobSubmissionService(sessions)
    service.submit(request(first_id))
    with pytest.raises(AsyncJobConflict, match="different request"):
        service.submit(request(second_id))
    with pytest.raises(AsyncJobConflict, match="different request"):
        service.submit(request(first_id, max_attempts=4))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AsyncJob)) == 1


def test_missing_document_and_unfinished_parse_do_not_create_jobs(sessions) -> None:
    service = AsyncJobSubmissionService(sessions)
    with pytest.raises(AsyncJobTargetError, match="document does not exist"):
        service.submit(request(999))
    document_id = add_document(sessions)
    with sessions() as session, session.begin():
        parse = DocumentParseJob(
            document_id=document_id,
            status=DocumentParseStatus.FAILED,
            source_sha256="a" * 64,
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        session.add(parse)
        session.flush()
        parse_id = parse.id
    with pytest.raises(AsyncJobTargetError, match="successful parse job"):
        service.submit(
            AsyncJobSubmission(
                idempotency_key="index",
                task=ChunkIndexTask(parse_job_id=parse_id),
            )
        )
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AsyncJob)) == 0


def test_successful_parse_can_be_submitted_for_indexing(sessions) -> None:
    document_id = add_document(sessions)
    with sessions() as session, session.begin():
        parse = DocumentParseJob(
            document_id=document_id,
            status=DocumentParseStatus.SUCCEEDED,
            source_sha256="a" * 64,
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        session.add(parse)
        session.flush()
        parse_id = parse.id
    submission = AsyncJobSubmission(
        idempotency_key="index",
        task=ChunkIndexTask(parse_job_id=parse_id, chunk_version=2),
    )
    result = AsyncJobSubmissionService(sessions).submit(submission)
    assert result.job.task.kind == "chunk_index"
    assert result.job.task.chunk_version == 2


def test_database_unique_constraint_is_final_concurrency_guard(sessions) -> None:
    document_id = add_document(sessions)
    AsyncJobSubmissionService(sessions).submit(request(document_id))
    with pytest.raises(IntegrityError), sessions() as session, session.begin():
        session.add(
            AsyncJob(
                idempotency_key="parse-report",
                request_sha256=request(document_id).request_sha256,
                task_kind="document_parse",
                task_payload=DocumentParseTask(document_id=document_id).model_dump(mode="json"),
            )
        )
        session.flush()
