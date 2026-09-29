"""Opt-in full PDF-to-evidence acceptance with local model and isolated stores."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from pymilvus import MilvusClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import DocumentChunk, DocumentIngestionJob
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider
from finsight.infrastructure.parsers.mineru import MinerUDocumentParser
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.document_chunk_indexing import DocumentChunkIndexingService
from finsight.services.document_chunk_persistence import DocumentChunkPersistenceService
from finsight.services.document_chunk_quality import audit_chunks
from finsight.services.document_chunk_source import ChunkSourceLoader
from finsight.services.document_ingestion import DocumentIngestionService
from finsight.services.document_parser import ParserOutput
from finsight.services.document_parsing import DocumentParsingService
from finsight.services.document_retrieval import DocumentRetrievalService
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.financial_chunker import FinancialTextChunker

pytestmark = pytest.mark.skipif(
    any(os.environ.get(name) != "1" for name in (
        "FINSIGHT_PG_INTEGRATION", "FINSIGHT_MILVUS_INTEGRATION",
        "FINSIGHT_MINERU_INTEGRATION", "FINSIGHT_BGE_INTEGRATION",
        "FINSIGHT_REAL_PDF_INTEGRATION",
    )),
    reason="Enable PostgreSQL, Milvus, MinerU, BGE and real-PDF integration flags",
)


def _normalize(output: ParserOutput, document_id: int):
    return normalize_mineru_output(output, document_id=document_id)


def test_real_pdf_chunks_are_retrievable_with_source_page(tmp_path: Path) -> None:
    settings = get_settings()
    sample = Path(os.environ["FINSIGHT_REAL_PDF_PATH"]).read_bytes()
    model_path = Path(os.environ["FINSIGHT_BGE_MODEL_PATH"])
    schema = f"finsight_retrieval_{uuid4().hex[:12]}"
    collection = f"finsight_retrieval_{uuid4().hex[:12]}"
    admin_engine = create_engine(settings.database_url)
    test_engine = None
    schema_created = False
    client = MilvusClient(uri=settings.milvus_uri)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        test_engine = create_engine(
            settings.database_url, connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        storage = LocalObjectStorage(tmp_path / "objects")
        upload_id = DocumentIngestionService(sessions, storage).ingest(
            sample,
            idempotency_key="day7-public-excerpt",
            title="Public financial disclosure excerpt (two-page test sample)",
            document_type=DocumentType.ANNOUNCEMENT,
            company_code="PUBLIC_SAMPLE",
            report_year=2024,
        )
        with sessions() as session:
            upload = session.get(DocumentIngestionJob, upload_id)
            assert upload is not None and upload.document_id is not None
            document_id = upload.document_id
        parse_job_id = DocumentParsingService(
            sessions, storage,
            MinerUDocumentParser(settings.mineru_api_url, max_wait_seconds=600),
            _normalize,
        ).parse_document(document_id)
        source = ChunkSourceLoader(sessions, storage).load(parse_job_id)
        drafts = FinancialTextChunker().chunk(source)
        quality = audit_chunks(source, drafts)
        assert quality.passed and quality.block_coverage_ratio == 1
        chunk_ids = DocumentChunkPersistenceService(sessions).save(source, drafts)
        assert len(chunk_ids) == len(drafts)

        embeddings = BGEM3EmbeddingProvider(
            model_path, device=os.environ.get("FINSIGHT_BGE_DEVICE", "cpu"), batch_size=2,
        )
        vectors = MilvusHybridVectorStore(
            settings.milvus_uri, collection_name=collection, client=client,
        )
        indexer = DocumentChunkIndexingService(sessions, embeddings, vectors, batch_size=2)
        first = indexer.index_parse_job(parse_job_id)
        assert indexer.index_parse_job(parse_job_id) == first
        assert len(first.vector_ids) == len(chunk_ids)
        with sessions() as session:
            saved = list(session.scalars(
                select(DocumentChunk).where(DocumentChunk.parse_job_id == parse_job_id)
            ))
            assert all(row.vector_id in first.vector_ids for row in saved)

        retrieval = DocumentRetrievalService(sessions, embeddings, vectors)
        criteria = DocumentSearchFilter(company_code="PUBLIC_SAMPLE", report_year=2024)
        cases = (
            ("What were average interest-earning assets in 2024?", "1,396,927", 2),
            ("How much was the total dividend per share for 2024?", "6.80", 1),
            ("How much did non-interest income increase in 2024?", "26%", 1),
        )
        passed = 0
        for question, expected, page in cases:
            result = retrieval.retrieve(question, criteria=criteria, limit=5)
            matches = [
                chunk for chunk in result.chunks
                if expected in chunk.content and chunk.page_start <= page <= chunk.page_end
            ]
            print(
                f"query={question!r}; hits={[(hit.chunk_id, hit.page_start, hit.score) for hit in result.chunks]}; "
                f"matched={bool(matches)}; rejected={result.trace.rejected_hits}"
            )
            assert all(hit.document_id == document_id and hit.source_blocks for hit in result.chunks)
            assert not result.trace.rejected_hits
            passed += bool(matches)
        assert passed == len(cases)
        print(f"Day7 retrieval acceptance: chunks={len(chunk_ids)}, recall@5={passed}/{len(cases)}")
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)
        if test_engine is not None:
            test_engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
