"""Opt-in round trip against an isolated Milvus hybrid collection."""

import os
from uuid import uuid4

import pytest
from pymilvus import MilvusClient

from finsight.core.config import get_settings
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.hybrid_vector_store import HybridChunkVector

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_MILVUS_INTEGRATION") != "1",
    reason="Set FINSIGHT_MILVUS_INTEGRATION=1 to test local Milvus",
)


def test_real_milvus_dense_sparse_hybrid_round_trip() -> None:
    collection = f"finsight_hybrid_step3_{uuid4().hex[:12]}"
    settings = get_settings()
    client = MilvusClient(uri=settings.milvus_uri)
    store = MilvusHybridVectorStore(
        settings.milvus_uri, collection_name=collection, dimension=3, client=client,
    )
    try:
        store.ensure_collection()
        store.ensure_collection()
        store.upsert(HybridChunkVector(
            "chunk-7-v1", 3, 7, 1, 2, 2, "BAAI/bge-m3", (1.0, 0.0, 0.0), {12: 0.7},
        ))
        store.upsert(HybridChunkVector(
            "chunk-8-v1", 4, 8, 1, 1, 1, "BAAI/bge-m3", (0.0, 1.0, 0.0), {23: 0.9},
        ))
        hits = store.search((1.0, 0.0, 0.0), {12: 0.7}, document_id=3, limit=5)
        assert [hit.vector_id for hit in hits] == ["chunk-7-v1"]
        assert hits[0].chunk_id == 7 and hits[0].page_start == 2
        assert [hit.vector_id for hit in store.search(
            (1.0, 0.0, 0.0), {12: 0.7}, document_ids=(4,), limit=5
        )] == ["chunk-8-v1"]
        assert store.search((1.0, 0.0, 0.0), {12: 0.7}, document_ids=()) == []
        store.delete("chunk-7-v1")
        assert store.search((1.0, 0.0, 0.0), {12: 0.7}, document_id=3, limit=5) == []
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)
