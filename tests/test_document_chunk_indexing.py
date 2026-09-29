from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.embedding import EmbeddingOutput, EmbeddingSpec, QueryEmbedding
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentParseJob
from finsight.services.document_chunk_indexing import (
    ChunkIndexingError,
    DocumentChunkIndexingService,
)


class FakeEmbeddings:
    def count_tokens(self, text: str) -> int:
        return len(text) + 2

    def encode_documents(self, inputs):
        return tuple(
            EmbeddingOutput(item.chunk_id, "BAAI/bge-m3", self.count_tokens(item.text),
                            (1.0, 0.0, 0.0), {12: 0.5})
            for item in inputs
        )

    def encode_query(self, query: str) -> QueryEmbedding:
        return QueryEmbedding("BAAI/bge-m3", 5, (1.0, 0.0, 0.0), {12: 0.5})


class FakeVectors:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.ready = False

    def ensure_collection(self) -> None:
        self.ready = True

    def upsert(self, vector) -> None:
        assert self.ready
        self.rows[vector.vector_id] = vector


class FailOnceVectors(FakeVectors):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def upsert(self, vector) -> None:
        self.attempts += 1
        if self.attempts == 2:
            raise RuntimeError("temporary Milvus outage")
        super().upsert(vector)


@pytest.fixture
def environment():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session)
    with sessions() as session, session.begin():
        document = Document(
            title="测试公告", document_type=DocumentType.ANNOUNCEMENT,
            object_key="test/index.pdf", content_sha256="a" * 64, file_size_bytes=10,
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
        for index, content in enumerate(("收入 100", "利润 20")):
            session.add(DocumentChunk(
                document_id=document.id, parse_job_id=job.id, chunk_index=index,
                chunk_version=1, kind="text", content=content,
                content_sha256=sha256(content.encode()).hexdigest(),
                page_start=1, page_end=1, section_path=["财务摘要"],
                source_blocks=[{"page_number": 1, "block_index": index}],
            ))
        job_id = job.id
    yield sessions, job_id
    engine.dispose()


def test_indexing_binds_vectors_and_replay_uses_same_ids(environment) -> None:
    sessions, job_id = environment
    store = FakeVectors()
    service = DocumentChunkIndexingService(
        sessions, FakeEmbeddings(), store,
        spec=EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20),
    )
    first = service.index_parse_job(job_id)
    assert service.index_parse_job(job_id) == first
    assert len(first.vector_ids) == len(store.rows) == 2
    with sessions() as session:
        rows = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
        assert [row.vector_id for row in rows] == list(first.vector_ids)


def test_oversized_chunk_fails_before_external_write(environment) -> None:
    sessions, job_id = environment
    with sessions() as session, session.begin():
        row = session.get(DocumentChunk, 2)
        assert row is not None
        row.content = "长" * 45
        row.content_sha256 = sha256(row.content.encode()).hexdigest()
    store = FakeVectors()
    service = DocumentChunkIndexingService(
        sessions, FakeEmbeddings(), store,
        spec=EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20),
    )
    with pytest.raises(ValueError, match="exceeds"):
        service.index_parse_job(job_id)
    assert store.rows == {} and not store.ready


def test_conflicting_existing_vector_id_is_rejected(environment) -> None:
    sessions, job_id = environment
    with sessions() as session, session.begin():
        row = session.get(DocumentChunk, 1)
        assert row is not None
        row.vector_id = "another-model-vector"
    store = FakeVectors()
    service = DocumentChunkIndexingService(sessions, FakeEmbeddings(), store)
    with pytest.raises(ChunkIndexingError, match="different vector identity"):
        service.index_parse_job(job_id)
    assert store.rows == {}


def test_partial_external_failure_can_replay_same_vector_ids(environment) -> None:
    sessions, job_id = environment
    store = FailOnceVectors()
    service = DocumentChunkIndexingService(
        sessions, FakeEmbeddings(), store,
        spec=EmbeddingSpec(dimension=3, model_max_tokens=100, batch_max_tokens=40, query_max_tokens=20),
    )
    with pytest.raises(RuntimeError, match="temporary Milvus outage"):
        service.index_parse_job(job_id)
    with sessions() as session:
        rows = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
        assert rows[0].vector_id is not None and rows[1].vector_id is None
    replay = service.index_parse_job(job_id)
    assert len(replay.vector_ids) == len(store.rows) == 2
    with sessions() as session:
        rows = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
        assert [row.vector_id for row in rows] == list(replay.vector_ids)
