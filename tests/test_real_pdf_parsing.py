"""Opt-in end-to-end check using an excerpt of a public financial disclosure."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.document_data import DocumentIngestionStatus, DocumentParseStatus, DocumentType
from finsight.domain.parsed_document import ParsedBlockType, ParsedDocument
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    DocumentChunk,
    DocumentIngestionJob,
    DocumentParseJob,
)
from finsight.infrastructure.parsers.mineru import MinerUDocumentParser
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.services.document_chunk_persistence import DocumentChunkPersistenceService
from finsight.services.document_chunk_quality import audit_chunks
from finsight.services.document_chunk_source import ChunkSourceLoader
from finsight.services.document_ingestion import DocumentIngestionService
from finsight.services.document_parser import ParserOutput
from finsight.services.document_parsing import DocumentParsingError, DocumentParsingService
from finsight.services.financial_chunker import FinancialTextChunker

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_REAL_PDF_INTEGRATION") != "1",
    reason="Set FINSIGHT_REAL_PDF_INTEGRATION=1 and FINSIGHT_REAL_PDF_PATH",
)


def _normalize(output: ParserOutput, document_id: int) -> ParsedDocument:
    return normalize_mineru_output(output, document_id=document_id)


def test_real_pdf_round_trip_and_invalid_pdf_failure(tmp_path: Path) -> None:
    sample_path = Path(os.environ["FINSIGHT_REAL_PDF_PATH"])
    sample = sample_path.read_bytes()
    assert sample.startswith(b"%PDF-")

    database_url = get_settings().database_url
    schema = f"finsight_pdf_step7_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url)
    test_engine = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        test_engine = create_engine(
            database_url, connect_args={"options": f"-csearch_path={schema}"}
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        storage = LocalObjectStorage(tmp_path / "objects")
        ingestion = DocumentIngestionService(sessions, storage)
        parsing = DocumentParsingService(
            sessions,
            storage,
            MinerUDocumentParser(get_settings().mineru_api_url, max_wait_seconds=600),
            _normalize,
        )

        upload_id = ingestion.ingest(
            sample,
            idempotency_key="real-hang-seng-excerpt",
            title="Hang Seng 2024 results disclosure excerpt: source pages 1 and 7",
            document_type=DocumentType.ANNOUNCEMENT,
        )
        with sessions() as session:
            upload = session.get(DocumentIngestionJob, upload_id)
            assert upload is not None and upload.document_id is not None
            document_id = upload.document_id

        parse_job_id = parsing.parse_document(document_id)
        with sessions() as session:
            job = session.get(DocumentParseJob, parse_job_id)
            upload = session.get(DocumentIngestionJob, upload_id)
            assert job is not None and upload is not None
            assert job.status == DocumentParseStatus.SUCCEEDED
            assert upload.status == DocumentIngestionStatus.SUCCEEDED
            assert job.page_count == 2
            assert all(
                key is not None and storage.exists(key)
                for key in (
                    job.markdown_key,
                    job.content_list_key,
                    job.middle_json_key,
                    job.parsed_document_key,
                )
            )
            assert job.parsed_document_key is not None
            parsed = ParsedDocument.model_validate_json(storage.get(job.parsed_document_key))
            tables = [
                block for block in parsed.pages[1].blocks
                if block.block_type == ParsedBlockType.TABLE
            ]
            assert tables
            assert any("1,396,927" in table.content for table in tables)
            assert "2024" in parsed.markdown and "2023" in parsed.markdown

        source = ChunkSourceLoader(sessions, storage).load(parse_job_id)
        chunks = FinancialTextChunker().chunk(source)
        quality = audit_chunks(source, chunks)
        assert quality.passed, quality.issues
        assert quality.block_coverage_ratio == 1
        assert quality.covered_page_count == 2
        assert quality.kind_counts.get("table", 0) >= 1
        table_chunks = [chunk for chunk in chunks if chunk.kind == "table"]
        assert any("1,396,927" in chunk.content for chunk in table_chunks)
        assert all(chunk.page_start == chunk.page_end == 2 for chunk in table_chunks)
        persistence = DocumentChunkPersistenceService(sessions)
        chunk_ids = persistence.save(source, chunks)
        assert persistence.save(source, chunks) == chunk_ids
        with sessions() as session:
            saved = list(session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ))
            assert len(saved) == len(chunks)
            assert [row.id for row in saved] == list(chunk_ids)
            assert any(row.kind == "table" and "1,396,927" in (row.content or "") for row in saved)
            assert all(row.parse_job_id == parse_job_id and row.source_blocks for row in saved)
        print(
            f"Day6 acceptance: pages={quality.page_count}, chunks={quality.chunk_count}, "
            f"tables={quality.kind_counts.get('table', 0)}, "
            f"coverage={quality.block_coverage_ratio:.0%}, "
            f"oversized_special={quality.oversized_special_count}"
        )

        invalid_upload_id = ingestion.ingest(
            b"not-a-pdf",
            idempotency_key="invalid-document-sample",
            title="Invalid PDF for failure-path test",
            document_type=DocumentType.ANNOUNCEMENT,
        )
        with sessions() as session:
            invalid_upload = session.get(DocumentIngestionJob, invalid_upload_id)
            assert invalid_upload is not None and invalid_upload.document_id is not None
            invalid_document_id = invalid_upload.document_id
        with pytest.raises(DocumentParsingError, match="job marked failed"):
            parsing.parse_document(invalid_document_id)
        with sessions() as session:
            failed = session.scalar(
                select(DocumentParseJob).where(DocumentParseJob.document_id == invalid_document_id)
            )
            invalid_upload = session.get(DocumentIngestionJob, invalid_upload_id)
            assert failed is not None and invalid_upload is not None
            assert failed.status == DocumentParseStatus.FAILED
            assert failed.error_code == "ValueError"
            assert invalid_upload.status == DocumentIngestionStatus.SUCCEEDED
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
