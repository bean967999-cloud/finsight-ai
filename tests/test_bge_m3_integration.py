"""Opt-in local model smoke test; no model download or Milvus writes."""

import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from finsight.domain.document_data import DocumentParseStatus, DocumentType
from finsight.domain.embedding import EmbeddingInput
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document, DocumentChunk, DocumentParseJob
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_BGE_INTEGRATION") != "1",
    reason="Set FINSIGHT_BGE_INTEGRATION=1 and FINSIGHT_BGE_MODEL_PATH",
)


def test_real_bge_m3_dense_sparse_and_token_count() -> None:
    model_path = Path(os.environ["FINSIGHT_BGE_MODEL_PATH"])
    assert (model_path / "pytorch_model.bin").is_file()
    provider = BGEM3EmbeddingProvider(
        model_path, device=os.environ.get("FINSIGHT_BGE_DEVICE", "cpu"), batch_size=1,
    )
    texts = ("2024 年营业收入为 100 亿元。", "2023 年营业收入为 80 亿元。")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        document = Document(
            title="向量化测试报告", document_type=DocumentType.ANNOUNCEMENT,
            object_key="test/embedding.pdf", content_sha256="a" * 64, file_size_bytes=10,
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
        for index, content in enumerate(texts):
            session.add(DocumentChunk(
                document_id=document.id, parse_job_id=job.id, chunk_index=index,
                chunk_version=1, kind="text", content=content,
                content_sha256=sha256(content.encode()).hexdigest(), page_start=1, page_end=1,
                section_path=["财务摘要"], source_blocks=[{"page_number": 1, "block_index": index}],
            ))
    with Session(engine) as session:
        saved = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)))
        inputs = tuple(
            EmbeddingInput(
                chunk_id=row.id, document_id=row.document_id, chunk_version=row.chunk_version,
                content_sha256=row.content_sha256, text=row.content or "",
            )
            for row in saved
        )
    engine.dispose()
    outputs = provider.encode_documents(inputs)
    query = provider.encode_query("2024 年营业收入是多少？")

    assert [output.chunk_id for output in outputs] == [1, 2]
    assert all(len(output.dense) == 1024 and output.sparse for output in outputs)
    assert all(output.token_count == provider.count_tokens(text) for output, text in zip(outputs, texts))
    assert len(query.dense) == 1024 and query.sparse and query.token_count > 0
    print(
        "BGE-M3 smoke:",
        f"document_tokens={[output.token_count for output in outputs]}",
        f"document_sparse_terms={[len(output.sparse) for output in outputs]}",
        f"query_tokens={query.token_count}",
        f"query_sparse_terms={len(query.sparse)}",
    )
