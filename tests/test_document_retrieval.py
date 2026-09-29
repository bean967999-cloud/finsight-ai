from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.embedding import EmbeddingSpec, QueryEmbedding
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Document,
    DocumentChunk,
    DocumentParseJob,
    KnowledgeBase,
    KnowledgeBaseDocument,
    Workspace,
)
from finsight.services.document_retrieval import DocumentRetrievalService
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.hybrid_vector_store import HybridVectorHit


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    def count_tokens(self, text: str) -> int:
        return 5

    def encode_documents(self, inputs):
        return ()

    def encode_query(self, query: str) -> QueryEmbedding:
        self.calls += 1
        return QueryEmbedding("BAAI/bge-m3", 5, (1.0, 0.0, 0.0), {12: 0.5})


class FakeVectors:
    def __init__(self, hits: list[HybridVectorHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def search(self, dense, sparse, **kwargs):
        self.calls.append(kwargs)
        return self.hits


@pytest.fixture
def environment():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    with sessions() as session, session.begin():
        for index, company in enumerate(("AAA", "BBB"), start=1):
            content = f"{company} 的营业收入为 {index}00 亿元。"
            document = Document(
                title=f"{company} 2024 年报", document_type=DocumentType.ANNUAL_REPORT,
                company_code=company, report_year=2024, report_period_end=date(2024, 12, 31),
                object_key=f"documents/{company}.pdf", content_sha256=f"{index:064x}",
                file_size_bytes=10,
            )
            session.add(document)
            session.flush()
            job = DocumentParseJob(
                document_id=document.id, status=DocumentParseStatus.SUCCEEDED,
                source_sha256=document.content_sha256, parser_name="fixture", parser_version="1",
                page_count=1, started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            )
            session.add(job)
            session.flush()
            session.add(DocumentChunk(
                document_id=document.id, parse_job_id=job.id, chunk_index=0,
                chunk_version=1, kind="text", content=content,
                content_sha256=sha256(content.encode()).hexdigest(), vector_id=f"vector-{index}",
                page_start=1, page_end=1, section_path=["经营情况"],
                source_blocks=[{"page_number": 1, "block_index": 0}],
            ))
    yield sessions
    engine.dispose()


def hit(index: int, *, version: int = 1) -> HybridVectorHit:
    return HybridVectorHit(f"vector-{index}", index, index, version, 1, 1, "BAAI/bge-m3", 0.03)


def service(environment, hits):
    embeddings = FakeEmbeddings()
    vectors = FakeVectors(hits)
    retrieval = DocumentRetrievalService(
        environment, embeddings, vectors,
        spec=EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20),
    )
    return retrieval, embeddings, vectors


def test_filtered_retrieval_reads_authoritative_text_and_source(environment) -> None:
    retrieval, embeddings, vectors = service(environment, [hit(1), hit(2)])
    result = retrieval.retrieve(
        "营业收入是多少", criteria=DocumentSearchFilter(company_code="AAA", report_year=2024),
    )
    assert embeddings.calls == 1
    assert vectors.calls[0]["document_ids"] == (1,)
    assert len(result.chunks) == 1
    assert result.chunks[0].document_title == "AAA 2024 年报"
    assert "100 亿元" in result.chunks[0].content
    assert result.chunks[0].source_blocks[0].page_number == 1
    assert result.trace.accepted_chunk_ids == (1,)
    assert result.trace.candidate_vector_ids == ("vector-1",)
    assert result.trace.rejected_hits == ()


def test_no_matching_documents_skips_embedding_and_milvus(environment) -> None:
    retrieval, embeddings, vectors = service(environment, [])
    result = retrieval.retrieve("营业收入", criteria=DocumentSearchFilter(company_code="UNKNOWN"))
    assert result.chunks == () and result.trace.filtered_document_ids == ()
    assert result.trace.query_token_count is None
    assert embeddings.calls == 0 and vectors.calls == []


def test_scoped_retrieval_rejects_foreign_vector_hits(environment) -> None:
    with environment() as session, session.begin():
        workspace = Workspace(name=f"team-{uuid4()}")
        session.add(workspace)
        session.flush()
        base = KnowledgeBase(workspace_id=workspace.id, name="private")
        session.add(base)
        session.flush()
        session.add(KnowledgeBaseDocument(knowledge_base_id=base.id, document_id=1))
        base_id = base.id
    retrieval, _, vectors = service(environment, [hit(1), hit(2)])
    result = retrieval.retrieve(
        "营业收入是多少", criteria=DocumentSearchFilter(knowledge_base_id=base_id)
    )
    assert vectors.calls[0]["document_ids"] == (1,)
    assert tuple(chunk.document_id for chunk in result.chunks) == (1,)
    assert result.trace.candidate_vector_ids == ("vector-1",)
    assert result.trace.rejected_hits == ()


def test_stale_version_and_changed_content_are_rejected_with_trace(environment) -> None:
    retrieval, _, _ = service(environment, [hit(1, version=2)])
    result = retrieval.retrieve("营业收入")
    assert result.chunks == ()
    assert "version" in result.trace.rejected_hits[0].reason

    with environment() as session, session.begin():
        row = session.get(DocumentChunk, 1)
        assert row is not None
        row.content = "正文已被修改"
    retrieval, _, _ = service(environment, [hit(1)])
    result = retrieval.retrieve("营业收入")
    assert result.chunks == ()
    assert result.trace.rejected_hits[0].reason == "chunk content digest mismatch"


def test_blank_query_and_invalid_limit_are_rejected(environment) -> None:
    retrieval, _, _ = service(environment, [])
    with pytest.raises(ValueError, match="empty"):
        retrieval.retrieve(" ")
    with pytest.raises(ValueError, match="limit"):
        retrieval.retrieve("收入", limit=0)
