"""Opt-in round trip against the project's real Milvus service."""

import os
from uuid import uuid4

import pytest
from pymilvus import MilvusClient

from finsight.core.config import get_settings
from finsight.infrastructure.vector.milvus import MilvusVectorStore
from finsight.services.vector_store import ChunkVector

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_MILVUS_INTEGRATION") != "1",
    reason="Set FINSIGHT_MILVUS_INTEGRATION=1 to test local Milvus",
)


def test_real_milvus_collection_upsert_search_delete() -> None:
    settings = get_settings()
    collection = f"finsight_step7_{uuid4().hex[:12]}"
    client = MilvusClient(uri=settings.milvus_uri)
    store = MilvusVectorStore(
        settings.milvus_uri, collection_name=collection, dimension=3, client=client
    )
    try:
        store.ensure_collection()
        store.ensure_collection()
        assert client.has_collection(collection_name=collection)

        store.upsert(ChunkVector("chunk-7", 3, 7, 2, 3, (1.0, 0.0, 0.0)))
        store.upsert(ChunkVector("chunk-8", 4, 8, 5, 5, (0.0, 1.0, 0.0)))

        hits = store.search((1.0, 0.0, 0.0), document_id=3, limit=5)
        assert [hit.vector_id for hit in hits] == ["chunk-7"]
        assert hits[0].chunk_id == 7
        assert hits[0].page_start == 2

        store.delete("chunk-7")
        assert store.search((1.0, 0.0, 0.0), document_id=3, limit=5) == []
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)
