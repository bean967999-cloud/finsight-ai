import pytest

from finsight.infrastructure.vector.milvus import MilvusVectorStore
from finsight.services.vector_store import ChunkVector, VectorStore


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, str]] = []

    def add_index(self, **kwargs: str) -> None:
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(self) -> None:
        self.collection_exists = False
        self.indexes = FakeIndexParams()
        self.created: dict | None = None
        self.upserted: dict | None = None
        self.searched: dict | None = None
        self.deleted: dict | None = None

    def has_collection(self, *, collection_name: str) -> bool:
        return self.collection_exists

    def prepare_index_params(self) -> FakeIndexParams:
        return self.indexes

    def create_collection(self, **kwargs) -> None:
        self.created = kwargs
        self.collection_exists = True

    def upsert(self, **kwargs) -> None:
        self.upserted = kwargs

    def search(self, **kwargs):
        self.searched = kwargs
        return [[{
            "vector_id": "chunk-7", "distance": 0.91,
            "entity": {
                "document_id": 3, "chunk_id": 7, "page_start": 2, "page_end": 3,
            },
        }]]

    def delete(self, **kwargs) -> None:
        self.deleted = kwargs


def test_collection_schema_and_cosine_index_are_created_once() -> None:
    client = FakeMilvusClient()
    store = MilvusVectorStore("http://localhost:59530", dimension=3, client=client)

    assert isinstance(store, VectorStore)
    store.ensure_collection()
    store.ensure_collection()

    assert client.created is not None
    assert client.created["collection_name"] == "finsight_document_chunks_v1"
    schema = client.created["schema"]
    fields = {field.name: field for field in schema.fields}
    assert set(fields) == {
        "vector_id", "document_id", "chunk_id", "page_start", "page_end", "dense_vector",
    }
    assert fields["vector_id"].is_primary is True
    assert fields["dense_vector"].params["dim"] == 3
    assert client.indexes.indexes == [{
        "field_name": "dense_vector", "index_type": "AUTOINDEX", "metric_type": "COSINE",
    }]


def test_upsert_search_and_delete_preserve_chunk_identity() -> None:
    client = FakeMilvusClient()
    store = MilvusVectorStore("http://localhost:59530", dimension=3, client=client)
    vector = ChunkVector(
        vector_id="chunk-7", document_id=3, chunk_id=7,
        page_start=2, page_end=3, values=(0.1, 0.2, 0.3),
    )

    store.upsert(vector)
    hits = store.search((0.1, 0.2, 0.3), document_id=3, limit=5)
    store.delete("chunk-7")

    assert client.upserted == {
        "collection_name": "finsight_document_chunks_v1",
        "data": {
            "vector_id": "chunk-7", "document_id": 3, "chunk_id": 7,
            "page_start": 2, "page_end": 3, "dense_vector": [0.1, 0.2, 0.3],
        },
    }
    assert client.searched is not None
    assert client.searched["filter"] == "document_id == 3"
    assert hits[0].vector_id == "chunk-7"
    assert (hits[0].document_id, hits[0].chunk_id, hits[0].page_start) == (3, 7, 2)
    assert hits[0].score == 0.91
    assert client.deleted == {
        "collection_name": "finsight_document_chunks_v1", "ids": ["chunk-7"],
    }


@pytest.mark.parametrize("values", [(0.1, 0.2), (0.1, float("nan"), 0.3)])
def test_wrong_dimension_and_non_finite_vectors_are_rejected(values) -> None:
    store = MilvusVectorStore("http://localhost:59530", dimension=3, client=FakeMilvusClient())
    with pytest.raises(ValueError, match="3 finite values"):
        store.search(values)


def test_chunk_and_search_filters_validate_inputs() -> None:
    with pytest.raises(ValueError, match="page range"):
        ChunkVector("chunk-7", 3, 7, 4, 2, (0.1, 0.2, 0.3))
    store = MilvusVectorStore("http://localhost:59530", dimension=3, client=FakeMilvusClient())
    with pytest.raises(ValueError, match="limit"):
        store.search((0.1, 0.2, 0.3), limit=0)
    with pytest.raises(ValueError, match="document_id"):
        store.search((0.1, 0.2, 0.3), document_id=-1)
