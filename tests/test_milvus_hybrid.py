import pytest

from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.hybrid_vector_store import HybridChunkVector, HybridVectorStore


class FakeIndexes:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add_index(self, **kwargs) -> None:
        self.items.append(kwargs)


class FakeClient:
    def __init__(self) -> None:
        self.exists = False
        self.indexes = FakeIndexes()
        self.created: dict | None = None
        self.upserted: dict | None = None
        self.hybrid_call: dict | None = None

    def has_collection(self, *, collection_name: str) -> bool:
        return self.exists

    def describe_collection(self, *, collection_name: str) -> dict:
        return {"fields": [
            *({"name": name} for name in (
                "vector_id", "document_id", "chunk_id", "chunk_version", "page_start",
                "page_end", "model_name", "sparse_vector",
            )),
            {"name": "dense_vector", "params": {"dim": 3}},
        ]}

    def prepare_index_params(self) -> FakeIndexes:
        return self.indexes

    def create_collection(self, **kwargs) -> None:
        self.created = kwargs
        self.exists = True

    def upsert(self, **kwargs) -> None:
        self.upserted = kwargs

    def hybrid_search(self, **kwargs):
        self.hybrid_call = kwargs
        return [[{
            "id": "chunk-7-v1", "distance": 0.03,
            "entity": {
                "document_id": 3, "chunk_id": 7, "chunk_version": 1,
                "page_start": 2, "page_end": 2, "model_name": "BAAI/bge-m3",
            },
        }]]

    def delete(self, **kwargs) -> None:
        pass


def test_new_collection_has_two_vector_fields_and_indexes() -> None:
    client = FakeClient()
    store = MilvusHybridVectorStore("http://localhost:59530", dimension=3, client=client)
    assert isinstance(store, HybridVectorStore)
    store.ensure_collection()
    store.ensure_collection()
    assert client.created is not None
    assert client.created["collection_name"] == "finsight_document_chunks_hybrid_v2"
    schema = client.created["schema"]
    fields = {field.name: field for field in schema.fields}
    assert fields["dense_vector"].params["dim"] == 3
    assert "sparse_vector" in fields and "chunk_version" in fields
    assert client.indexes.items == [
        {"field_name": "dense_vector", "index_type": "AUTOINDEX", "metric_type": "COSINE"},
        {
            "field_name": "sparse_vector", "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "IP", "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
        },
    ]


def test_hybrid_upsert_and_search_keep_source_identity() -> None:
    client = FakeClient()
    store = MilvusHybridVectorStore("http://localhost:59530", dimension=3, client=client)
    vector = HybridChunkVector(
        "chunk-7-v1", 3, 7, 1, 2, 2, "BAAI/bge-m3", (1.0, 0.0, 0.0), {12: 0.7},
    )
    store.upsert(vector)
    assert client.upserted is not None
    assert client.upserted["data"]["sparse_vector"] == {12: 0.7}
    hits = store.search((1.0, 0.0, 0.0), {12: 0.7}, limit=3, document_id=3)
    assert len(hits) == 1 and hits[0].chunk_id == 7
    assert hits[0].chunk_version == 1 and hits[0].page_start == 2
    assert client.hybrid_call is not None
    assert len(client.hybrid_call["reqs"]) == 2
    assert client.hybrid_call["limit"] == 3


def test_invalid_vectors_and_filters_are_rejected() -> None:
    store = MilvusHybridVectorStore("http://localhost:59530", dimension=3, client=FakeClient())
    with pytest.raises(ValueError, match="3 finite"):
        store.search((1.0, 0.0), {12: 0.7})
    with pytest.raises(ValueError, match="sparse"):
        store.search((1.0, 0.0, 0.0), {12: -1.0})
    with pytest.raises(ValueError, match="document_id"):
        store.search((1.0, 0.0, 0.0), {12: 0.7}, document_id=-1)


def test_existing_collection_with_wrong_dimension_is_rejected() -> None:
    client = FakeClient()
    client.exists = True
    store = MilvusHybridVectorStore("http://localhost:59530", dimension=1024, client=client)
    with pytest.raises(ValueError, match="expected hybrid schema"):
        store.ensure_collection()


def test_document_id_set_filter_and_empty_set_never_search_everything() -> None:
    client = FakeClient()
    store = MilvusHybridVectorStore("http://localhost:59530", dimension=3, client=client)
    assert store.search((1.0, 0.0, 0.0), {12: 0.7}, document_ids=()) == []
    assert client.hybrid_call is None
    store.search((1.0, 0.0, 0.0), {12: 0.7}, document_ids=(4, 3, 4))
    assert client.hybrid_call is not None
    assert all(request.expr == "document_id in [3, 4]" for request in client.hybrid_call["reqs"])
    with pytest.raises(ValueError, match="not both"):
        store.search((1.0, 0.0, 0.0), {12: 0.7}, document_id=3, document_ids=(3,))
    with pytest.raises(ValueError, match="positive IDs"):
        store.search((1.0, 0.0, 0.0), {12: 0.7}, document_ids=(0,))
