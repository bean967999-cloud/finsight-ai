"""Opt-in PostgreSQL-to-Milvus business filter round trip."""

import os
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from pymilvus import MilvusClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finsight.core.config import get_settings
from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.embedding import EmbeddingSpec, QueryEmbedding
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentParseJob
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.document_retrieval import DocumentRetrievalService
from finsight.services.document_search_filter import DocumentFilterResolver, DocumentSearchFilter
from finsight.services.hybrid_vector_store import HybridChunkVector

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1"
    or os.environ.get("FINSIGHT_MILVUS_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 and FINSIGHT_MILVUS_INTEGRATION=1",
)


class FixedQueryEmbedding:
    def count_tokens(self, text: str) -> int:
        return 5

    def encode_documents(self, inputs):
        return ()

    def encode_query(self, query: str) -> QueryEmbedding:
        return QueryEmbedding("BAAI/bge-m3", 5, (1.0, 0.0, 0.0), {12: 0.5})


def test_postgres_metadata_filters_milvus_hybrid_candidates() -> None:
    settings = get_settings()
    schema = f"finsight_filter_{uuid4().hex[:12]}"
    collection = f"finsight_filter_{uuid4().hex[:12]}"
    admin_engine = create_engine(settings.database_url)
    test_engine = None
    client = MilvusClient(uri=settings.milvus_uri)
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_created = True
        test_engine = create_engine(
            settings.database_url, connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session)
        documents = [
            ("AAA", 2024), ("AAA", 2023), ("BBB", 2024),
        ]
        with sessions() as session, session.begin():
            for index, (company, year) in enumerate(documents):
                document = Document(
                    title=f"{company} {year} annual", document_type=DocumentType.ANNUAL_REPORT,
                    company_code=company, report_year=year,
                    report_period_end=date(year, 12, 31),
                    object_key=f"filter/{index}.pdf", content_sha256=f"{index:064x}",
                    file_size_bytes=10,
                )
                session.add(document)
                session.flush()
                job = DocumentParseJob(
                    document_id=document.id, status=DocumentParseStatus.SUCCEEDED,
                    source_sha256=document.content_sha256,
                    parser_name="fixture", parser_version="1", page_count=1,
                    started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
                )
                session.add(job)
                session.flush()
                content = f"{company} {year} 年营业收入为 {index + 1}00 亿元。"
                session.add(DocumentChunk(
                    document_id=document.id, parse_job_id=job.id, chunk_index=0,
                    chunk_version=1, kind="text", content=content,
                    content_sha256=sha256(content.encode()).hexdigest(),
                    vector_id=f"chunk-{document.id}", page_start=1, page_end=1,
                    section_path=["财务摘要"],
                    source_blocks=[{"page_number": 1, "block_index": 0}],
                ))
        store = MilvusHybridVectorStore(
            settings.milvus_uri, collection_name=collection, dimension=3, client=client,
        )
        store.ensure_collection()
        for document_id in (1, 2, 3):
            store.upsert(HybridChunkVector(
                f"chunk-{document_id}", document_id, document_id, 1, 1, 1,
                "BAAI/bge-m3", (1.0, 0.0, 0.0), {12: 0.5},
            ))
        resolver = DocumentFilterResolver(sessions)
        ids = resolver.resolve(DocumentSearchFilter(
            company_code="AAA", document_type=DocumentType.ANNUAL_REPORT,
            report_year=2024,
        ))
        assert ids == (1,)
        hits = store.search((1.0, 0.0, 0.0), {12: 0.5}, document_ids=ids)
        assert [hit.document_id for hit in hits] == [1]
        retrieval = DocumentRetrievalService(
            sessions, FixedQueryEmbedding(), store,
            spec=EmbeddingSpec(
                dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20,
            ),
        )
        response = retrieval.retrieve(
            "2024 年收入", criteria=DocumentSearchFilter(
                company_code="AAA", document_type=DocumentType.ANNUAL_REPORT,
                report_year=2024,
            ),
        )
        assert len(response.chunks) == 1
        assert "AAA 2024 年营业收入为 100 亿元" in response.chunks[0].content
        assert response.chunks[0].source_blocks[0].page_number == 1
        assert response.trace.accepted_chunk_ids == (1,)
        no_ids = resolver.resolve(DocumentSearchFilter(company_code="UNKNOWN"))
        assert no_ids == ()
        assert store.search((1.0, 0.0, 0.0), {12: 0.5}, document_ids=no_ids) == []
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)
        if test_engine is not None:
            test_engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
