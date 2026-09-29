from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.document_data import DocumentIngestionStatus, DocumentParseStatus, DocumentType
from finsight.domain.parsed_document import ParsedDocument
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentIngestionJob, DocumentParseJob
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.document_ingestion import DocumentIngestionService
from finsight.services.document_parser import ParserOutput
from finsight.services.document_parsing import DocumentParsingError, DocumentParsingService

PDF = b"%PDF-1.7\nexample"


class FakeParser:
    def __init__(self, digest: str, *, fail: bool = False) -> None:
        self.digest = digest
        self.fail = fail

    def parse_pdf(self, content: bytes) -> ParserOutput:
        assert content == PDF
        if self.fail:
            raise RuntimeError("parser unavailable")
        return ParserOutput(
            source_sha256=self.digest,
            task_id="12345678-1234-5678-1234-567812345678",
            parser_name="mineru",
            parser_version="3.4.5",
            backend="pipeline",
            markdown="# 报告\n\n正文",
            content_list_json='[{"type":"text","text":"报告","text_level":1,"page_idx":0}]',
            middle_json='{"pdf_info":[{"page_idx":0}]}',
        )


def normalize(output: ParserOutput, document_id: int) -> ParsedDocument:
    return normalize_mineru_output(output, document_id=document_id)


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
    upload_id = DocumentIngestionService(sessions, storage).ingest(
        PDF,
        idempotency_key="upload-1",
        title="Test report",
        document_type=DocumentType.ANNUAL_REPORT,
        company_code="TEST",
        report_year=2025,
        report_period_end=date(2025, 12, 31),
    )
    with sessions() as session:
        upload = session.get(DocumentIngestionJob, upload_id)
        assert upload is not None and upload.document_id is not None
        document_id = upload.document_id
        document = session.get(Document, document_id)
        assert document is not None
        digest = document.content_sha256
    yield sessions, storage, document_id, upload_id, digest
    engine.dispose()


def test_parse_persists_four_artifacts_without_changing_upload_state(environment) -> None:
    sessions, storage, document_id, upload_id, digest = environment
    service = DocumentParsingService(sessions, storage, FakeParser(digest), normalize)

    job_id = service.parse_document(document_id)

    with sessions() as session:
        job = session.get(DocumentParseJob, job_id)
        upload = session.get(DocumentIngestionJob, upload_id)
        assert job is not None and upload is not None
        assert job.status == DocumentParseStatus.SUCCEEDED
        assert upload.status == DocumentIngestionStatus.SUCCEEDED
        assert job.page_count == 1
        assert job.parser_version == "3.4.5"
        assert job.started_at is not None and job.finished_at is not None
        assert job.markdown_key is not None
        assert job.content_list_key is not None
        assert job.middle_json_key is not None
        assert job.parsed_document_key is not None
        assert storage.get(job.markdown_key).decode("utf-8") == "# 报告\n\n正文"
        assert b"page_idx" in storage.get(job.content_list_key)
        assert b"pdf_info" in storage.get(job.middle_json_key)
        parsed = ParsedDocument.model_validate_json(storage.get(job.parsed_document_key))
        assert parsed.document_id == document_id
        assert parsed.source_sha256 == digest


def test_each_retry_has_its_own_job_and_artifact_keys(environment) -> None:
    sessions, storage, document_id, _, digest = environment
    service = DocumentParsingService(sessions, storage, FakeParser(digest), normalize)
    first = service.parse_document(document_id)
    second = service.parse_document(document_id)

    with sessions() as session:
        jobs = list(session.scalars(select(DocumentParseJob).order_by(DocumentParseJob.id)))
        assert [job.id for job in jobs] == [first, second]
        assert jobs[0].parsed_document_key != jobs[1].parsed_document_key
        assert storage.exists(jobs[0].parsed_document_key)
        assert storage.exists(jobs[1].parsed_document_key)


@pytest.mark.parametrize("failure", ["parser", "digest", "normalizer"])
def test_failure_marks_only_parse_job_failed(environment, failure: str) -> None:
    sessions, storage, document_id, upload_id, digest = environment
    parser = FakeParser("b" * 64 if failure == "digest" else digest, fail=failure == "parser")

    def broken_normalizer(output: ParserOutput, document_id: int) -> ParsedDocument:
        if failure == "normalizer":
            raise ValueError("bad content")
        return normalize(output, document_id)

    service = DocumentParsingService(sessions, storage, parser, broken_normalizer)
    with pytest.raises(DocumentParsingError, match="job marked failed"):
        service.parse_document(document_id)

    with sessions() as session:
        job = session.scalar(select(DocumentParseJob))
        upload = session.get(DocumentIngestionJob, upload_id)
        assert job is not None and upload is not None
        assert job.status == DocumentParseStatus.FAILED
        assert job.error_code is not None
        assert job.parsed_document_key is None
        assert upload.status == DocumentIngestionStatus.SUCCEEDED


def test_missing_document_does_not_create_parse_job(environment) -> None:
    sessions, storage, _, _, digest = environment
    service = DocumentParsingService(sessions, storage, FakeParser(digest), normalize)
    with pytest.raises(DocumentParsingError, match="does not exist"):
        service.parse_document(9999)
    with sessions() as session:
        assert session.scalar(select(DocumentParseJob)) is None


def test_partial_artifact_write_is_cleaned_up_and_job_failed(environment, monkeypatch) -> None:
    sessions, storage, document_id, upload_id, digest = environment
    original_put = storage.put
    writes: list[str] = []

    def fail_third_parse_write(key: str, content: bytes):
        if key.startswith("parsing/"):
            writes.append(key)
            if len(writes) == 3:
                raise OSError("disk unavailable")
        return original_put(key, content)

    monkeypatch.setattr(storage, "put", fail_third_parse_write)
    service = DocumentParsingService(sessions, storage, FakeParser(digest), normalize)
    with pytest.raises(DocumentParsingError, match="job marked failed"):
        service.parse_document(document_id)

    with sessions() as session:
        job = session.scalar(select(DocumentParseJob))
        upload = session.get(DocumentIngestionJob, upload_id)
        assert job is not None and upload is not None
        assert job.status == DocumentParseStatus.FAILED
        assert job.error_code == "OSError"
        assert job.markdown_key is None
        assert upload.status == DocumentIngestionStatus.SUCCEEDED
    assert len(writes) == 3
    assert not storage.exists(writes[0])
    assert not storage.exists(writes[1])
