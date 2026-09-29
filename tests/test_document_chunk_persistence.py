"""Chunk persistence, versioning, replay, and rollback."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.parsed_document import ParsedBlock, ParsedDocument, ParsedPage
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentParseJob
from finsight.services.document_chunk_persistence import (
    ChunkPersistenceError,
    DocumentChunkPersistenceService,
)
from finsight.services.document_chunk_source import ChunkSource
from finsight.services.financial_chunker import FinancialTextChunker


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
            title="测试报告", document_type=DocumentType.ANNOUNCEMENT,
            object_key="documents/test.pdf", content_sha256="a" * 64, file_size_bytes=10,
        )
        session.add(document)
        session.flush()
        job = DocumentParseJob(
            document_id=document.id, status=DocumentParseStatus.SUCCEEDED,
            source_sha256="a" * 64, parser_name="fixture", parser_version="1",
            page_count=1, parsed_document_key="parsing/test.json",
            started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
        )
        session.add(job)
        session.flush()
        source = ChunkSource(
            parse_job_id=job.id, document_id=document.id, source_sha256="a" * 64,
            parsed_document=ParsedDocument(
                document_id=document.id, source_sha256="a" * 64,
                parser_name="fixture", parser_version="1", page_count=1,
                markdown="test", pages=(ParsedPage(page_number=1, blocks=(
                    ParsedBlock(block_index=0, block_type="heading", content="财务摘要", heading_level=1),
                    ParsedBlock(block_index=1, block_type="text", content="收入为一百万元。"),
                    ParsedBlock(
                        block_index=2, block_type="table", table_format="html",
                        content="<table><tr><th>项目</th><th>金额</th></tr><tr><td>收入</td><td>100</td></tr></table>",
                    ),
                )),),
            ),
            title="测试报告", document_type=DocumentType.ANNOUNCEMENT,
            company_code=None, security_symbol=None, report_year=None,
            report_period_end=None, source_url=None,
        )
    yield sessions, source
    engine.dispose()


def test_save_replay_and_new_version(environment) -> None:
    sessions, source = environment
    service = DocumentChunkPersistenceService(sessions)
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source)

    ids = service.save(source, chunks)
    assert len(ids) == 2
    assert service.save(source, chunks) == ids
    with sessions() as session:
        rows = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
        assert len(rows) == 2
        assert rows[0].content == chunks[0].content
        assert rows[0].section_path == ["财务摘要"]
        assert rows[0].source_blocks == [{"page_number": 1, "block_index": 0}, {"page_number": 1, "block_index": 1}]
        assert rows[1].kind == "table"
        assert rows[1].table_format == "html"
        assert rows[1].content_sha256 == chunks[1].content_sha256
        assert rows[1].parse_job_id == source.parse_job_id

    new_ids = service.save(source, FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source, chunk_version=2))
    assert set(new_ids).isdisjoint(ids)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 4


def test_same_version_changed_content_rejected_without_overwrite(environment) -> None:
    sessions, source = environment
    service = DocumentChunkPersistenceService(sessions)
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source)
    ids = service.save(source, chunks)

    with pytest.raises(ChunkPersistenceError, match="different data"):
        service.save(source, (chunks[0].model_copy(update={"content": "不同正文"}), chunks[1]))
    assert service.save(source, chunks) == ids


def test_invalid_batch_rejected_atomically(environment) -> None:
    sessions, source = environment
    service = DocumentChunkPersistenceService(sessions)
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source)
    with pytest.raises(ChunkPersistenceError, match="noncontiguous"):
        service.save(source, (chunks[0], chunks[1].model_copy(update={"chunk_index": 3})))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 0


def test_source_job_must_still_be_valid_at_save_time(environment) -> None:
    sessions, source = environment
    chunks = FinancialTextChunker(max_chars=100, overlap_chars=10).chunk(source)
    with sessions() as session, session.begin():
        job = session.get(DocumentParseJob, source.parse_job_id)
        assert job is not None
        job.status = DocumentParseStatus.FAILED
    with pytest.raises(ChunkPersistenceError, match="no longer valid"):
        DocumentChunkPersistenceService(sessions).save(source, chunks)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 0
