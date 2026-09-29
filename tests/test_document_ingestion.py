from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.document_data import DocumentIngestionStatus, DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentIngestionJob
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.document_deduplication import fingerprint_document
from finsight.services.document_ingestion import DocumentIngestionError, DocumentIngestionService


@pytest.fixture
def environment(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    storage = LocalObjectStorage(tmp_path / "objects")
    yield sessions, storage
    engine.dispose()


def upload(service: DocumentIngestionService, content: bytes, key: str, **kwargs: str) -> int:
    return service.ingest(
        content,
        idempotency_key=key,
        title=kwargs.get("title", "Example annual report"),
        document_type=DocumentType.ANNUAL_REPORT,
        company_code="CMB",
        report_year=2025,
        report_period_end=date(2025, 12, 31),
    )


def test_ingest_stores_file_document_and_successful_job(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nannual report"

    job_id = upload(service, content, "first-request")

    with sessions() as session:
        job = session.get(DocumentIngestionJob, job_id)
        assert job is not None
        assert job.status == DocumentIngestionStatus.SUCCEEDED
        assert job.attempt_count == 1
        assert job.request_sha256 is not None
        assert job.started_at is not None and job.finished_at is not None
        document = session.get(Document, job.document_id)
        assert document is not None
        assert document.file_size_bytes == len(content)
        assert storage.get(document.object_key) == content


def test_same_key_same_request_reuses_job_without_rewriting(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nannual report"
    first = upload(service, content, "same-request")

    second = upload(service, content, "same-request")

    assert second == first
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentIngestionJob)) == 1


def test_same_key_different_request_is_rejected(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    upload(service, b"%PDF-1.7\noriginal", "same-key")

    with pytest.raises(DocumentIngestionError, match="different request"):
        upload(service, b"%PDF-1.7\nchanged", "same-key")
    with pytest.raises(DocumentIngestionError, match="different request"):
        upload(service, b"%PDF-1.7\noriginal", "same-key", title="Changed title")


def test_different_key_same_content_reuses_document(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nshared"
    first = upload(service, content, "request-a")
    second = upload(service, content, "request-b")

    assert first != second
    with sessions() as session:
        jobs = list(session.scalars(select(DocumentIngestionJob).order_by(DocumentIngestionJob.id)))
        assert len(jobs) == 2
        assert jobs[0].document_id == jobs[1].document_id
        assert session.scalar(select(func.count()).select_from(Document)) == 1


def test_storage_failure_marks_job_failed_without_document(environment) -> None:
    sessions, storage = environment

    class FailingStorage(LocalObjectStorage):
        def put(self, key: str, content: bytes):
            raise OSError("private storage details")

    failing_storage = FailingStorage(storage._root)
    service = DocumentIngestionService(sessions, failing_storage)

    with pytest.raises(DocumentIngestionError, match="job marked failed"):
        upload(service, b"%PDF-1.7\nfailing", "failure-request")

    with sessions() as session:
        job = session.scalar(select(DocumentIngestionJob))
        assert job is not None and job.status == DocumentIngestionStatus.FAILED
        assert job.error_code == "OSError"
        assert job.finished_at is not None
        assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_existing_key_with_wrong_bytes_fails_without_overwrite(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nexpected"
    key = fingerprint_document(content).object_key
    storage.put(key, b"wrong bytes")

    with pytest.raises(DocumentIngestionError, match="job marked failed"):
        upload(service, content, "corrupt-object")

    assert storage.get(key) == b"wrong bytes"


def test_database_failure_marks_job_failed_and_new_attempt_reuses_stored_bytes(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nretryable"
    object_key = fingerprint_document(content).object_key

    def fail_insert(_mapper, _connection, _target) -> None:
        raise RuntimeError("simulated database failure")

    event.listen(Document, "before_insert", fail_insert)
    try:
        with pytest.raises(DocumentIngestionError, match="job marked failed"):
            upload(service, content, "failed-attempt")
    finally:
        event.remove(Document, "before_insert", fail_insert)

    with sessions() as session:
        failed = session.scalar(select(DocumentIngestionJob))
        assert failed is not None and failed.status == DocumentIngestionStatus.FAILED
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert storage.get(object_key) == content

    with pytest.raises(DocumentIngestionError, match="failed"):
        upload(service, content, "failed-attempt")

    retried_job_id = upload(service, content, "new-attempt")
    with sessions() as session:
        retried = session.get(DocumentIngestionJob, retried_job_id)
        assert retried is not None and retried.status == DocumentIngestionStatus.SUCCEEDED
        assert session.scalar(select(func.count()).select_from(Document)) == 1


def test_missing_object_is_restored_for_same_content_new_request(environment) -> None:
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nrestored"
    first = upload(service, content, "original-request")
    object_key = fingerprint_document(content).object_key
    storage.delete(object_key)

    second = upload(service, content, "restore-request")

    assert second != first
    assert storage.get(object_key) == content
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1


def test_scope_constraint_rejects_existing_duplicate_without_grant(environment):
    sessions, storage = environment
    service = DocumentIngestionService(sessions, storage)
    content = b"%PDF-1.7\nscoped"
    first = upload(service, content, "scoped-first")
    with sessions() as session:
        document_id = session.get(DocumentIngestionJob, first).document_id
    with pytest.raises(DocumentIngestionError):
        service.ingest(content, idempotency_key="unauthorized-duplicate", title="Other",
                       document_type=DocumentType.ANNOUNCEMENT,
                       allowed_existing_document_ids=frozenset())
    allowed = service.ingest(content, idempotency_key="authorized-duplicate", title="Other",
                             document_type=DocumentType.ANNOUNCEMENT,
                             allowed_existing_document_ids=frozenset({document_id}))
    with sessions() as session:
        assert session.get(DocumentIngestionJob, allowed).document_id == document_id
        assert session.scalar(select(func.count()).select_from(Document)) == 1
