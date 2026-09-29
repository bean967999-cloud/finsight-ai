from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.document_chunking import ChunkDraft, ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentParseJob
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.document_chunk_source import ChunkSourceError, ChunkSourceLoader

FIXTURE = Path(__file__).parent / "Fixtures" / "Parsing" / "AnnualReportResult.json"
ARTIFACT_KEY = "parsing/test/parsed-document.json"


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
    storage.put(ARTIFACT_KEY, FIXTURE.read_bytes())
    with sessions() as session, session.begin():
        document = Document(
            title="Test report",
            document_type=DocumentType.ANNOUNCEMENT,
            company_code="TEST",
            security_symbol="TEST.HK",
            report_year=2025,
            object_key="documents/test.pdf",
            content_sha256="a" * 64,
            file_size_bytes=10,
        )
        session.add(document)
        session.flush()
        job = DocumentParseJob(
            document_id=document.id,
            status=DocumentParseStatus.SUCCEEDED,
            source_sha256="a" * 64,
            parser_name="fixture",
            parser_version="1",
            page_count=2,
            parsed_document_key=ARTIFACT_KEY,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield sessions, storage, job_id
    engine.dispose()


def test_loader_returns_only_matching_successful_parse(environment) -> None:
    sessions, storage, job_id = environment
    source = ChunkSourceLoader(sessions, storage).load(job_id)

    assert source.parse_job_id == job_id
    assert source.document_id == 1
    assert source.title == "Test report"
    assert source.document_type == DocumentType.ANNOUNCEMENT
    assert source.company_code == "TEST"
    assert source.security_symbol == "TEST.HK"
    assert source.report_year == 2025
    assert source.parsed_document.page_count == 2
    assert source.parsed_document.pages[1].blocks[1].block_type.value == "table"


@pytest.mark.parametrize(
    "change, message",
    [
        ({"status": DocumentParseStatus.FAILED}, "not succeeded"),
        ({"status": DocumentParseStatus.RUNNING}, "not succeeded"),
        ({"source_sha256": "b" * 64}, "does not match source document"),
        ({"parsed_document_key": None}, "missing required result metadata"),
        ({"page_count": 3}, "does not match parse job"),
        ({"parser_version": "wrong"}, "does not match parse job"),
    ],
)
def test_loader_rejects_unusable_parse_jobs(environment, change, message) -> None:
    sessions, storage, job_id = environment
    with sessions() as session, session.begin():
        job = session.get(DocumentParseJob, job_id)
        assert job is not None
        for name, value in change.items():
            setattr(job, name, value)

    with pytest.raises(ChunkSourceError, match=message):
        ChunkSourceLoader(sessions, storage).load(job_id)


def test_loader_rejects_missing_or_corrupt_artifact(environment) -> None:
    sessions, storage, job_id = environment
    storage.put(ARTIFACT_KEY, b"not JSON")
    with pytest.raises(ChunkSourceError, match="unavailable or invalid"):
        ChunkSourceLoader(sessions, storage).load(job_id)


def test_loader_requires_explicit_existing_job(environment) -> None:
    sessions, storage, _ = environment
    loader = ChunkSourceLoader(sessions, storage)
    with pytest.raises(ValueError, match="positive"):
        loader.load(0)
    with pytest.raises(ChunkSourceError, match="does not exist"):
        loader.load(999)


def test_chunk_draft_carries_exact_source_block_trace() -> None:
    chunk = ChunkDraft(
        document_id=7,
        parse_job_id=11,
        chunk_index=0,
        chunk_version=2,
        kind=ChunkKind.TABLE,
        table_format="html",
        content="<table><tr><td>120</td></tr></table>",
        page_start=2,
        page_end=3,
        section_path=("年度报告", "财务数据"),
        source_blocks=(
            SourceBlockRef(page_number=2, block_index=3),
            SourceBlockRef(page_number=3, block_index=0),
        ),
    )
    assert chunk.content_sha256 == sha256(chunk.content.encode("utf-8")).hexdigest()
    assert chunk.page_start == 2 and chunk.page_end == 3


@pytest.mark.parametrize(
    "change, message",
    [
        ({"content": "  "}, "content"),
        ({"source_blocks": []}, "source_blocks"),
        ({"source_blocks": [{"page_number": 1, "block_index": 0}]}, "page range"),
        (
            {"source_blocks": [
                {"page_number": 2, "block_index": 1},
                {"page_number": 2, "block_index": 0},
            ]},
            "reading order",
        ),
        ({"section_path": ("财务数据", " ")}, "section_path"),
        ({"kind": ChunkKind.TABLE}, "table_format"),
        ({"kind": ChunkKind.IMAGE_REFERENCE}, "asset_path"),
        (
            {"kind": ChunkKind.IMAGE_REFERENCE, "asset_path": "../outside.png"},
            "safe relative path",
        ),
    ],
)
def test_chunk_draft_rejects_untraceable_content(change, message) -> None:
    values = {
        "document_id": 7,
        "parse_job_id": 11,
        "chunk_index": 0,
        "kind": ChunkKind.TEXT,
        "content": "正文",
        "page_start": 2,
        "page_end": 2,
        "source_blocks": [{"page_number": 2, "block_index": 0}],
    }
    values.update(change)
    with pytest.raises(ValidationError, match=message):
        ChunkDraft.model_validate(values)
