"""Milvus 2.5 dense/sparse collection and rank-fusion adapter."""

from math import isfinite
from typing import Any

from pymilvus import (  # type: ignore[import-untyped]
    AnnSearchRequest,
    DataType,
    MilvusClient,
    RRFRanker,
)

from finsight.services.hybrid_vector_store import HybridChunkVector, HybridVectorHit


class MilvusHybridVectorStore:
    def __init__(
        self,
        uri: str,
        *,
        collection_name: str = "finsight_document_chunks_hybrid_v2",
        dimension: int = 1024,
        client: Any | None = None,
    ) -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        if not collection_name or not collection_name.replace("_", "").isalnum():
            raise ValueError("collection name must be alphanumeric or underscores")
        self._client = client if client is not None else MilvusClient(uri=uri)
        self._collection = collection_name
        self._dimension = dimension

    def ensure_collection(self) -> None:
        if self._client.has_collection(collection_name=self._collection):
            description = self._client.describe_collection(collection_name=self._collection)
            fields = {field["name"]: field for field in description["fields"]}
            required = {
                "vector_id", "document_id", "chunk_id", "chunk_version", "page_start",
                "page_end", "model_name", "dense_vector", "sparse_vector",
            }
            if not required <= fields.keys() or int(
                fields["dense_vector"].get("params", {}).get("dim", -1)
            ) != self._dimension:
                raise ValueError("existing collection is not the expected hybrid schema")
            return
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("vector_id", DataType.VARCHAR, is_primary=True, max_length=100)
        schema.add_field("document_id", DataType.INT64)
        schema.add_field("chunk_id", DataType.INT64)
        schema.add_field("chunk_version", DataType.INT64)
        schema.add_field("page_start", DataType.INT64)
        schema.add_field("page_end", DataType.INT64)
        schema.add_field("model_name", DataType.VARCHAR, max_length=100)
        schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=self._dimension)
        schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
        indexes = self._client.prepare_index_params()
        indexes.add_index(
            field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        indexes.add_index(
            field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        self._client.create_collection(
            collection_name=self._collection, schema=schema, index_params=indexes,
        )

    def upsert(self, vector: HybridChunkVector) -> None:
        self._validate_dense(vector.dense)
        self._client.upsert(
            collection_name=self._collection,
            data={
                "vector_id": vector.vector_id,
                "document_id": vector.document_id,
                "chunk_id": vector.chunk_id,
                "chunk_version": vector.chunk_version,
                "page_start": vector.page_start,
                "page_end": vector.page_end,
                "model_name": vector.model_name,
                "dense_vector": list(vector.dense),
                "sparse_vector": vector.sparse,
            },
        )

    def search(
        self, dense: tuple[float, ...], sparse: dict[int, float], *,
        limit: int = 10, document_id: int | None = None,
        document_ids: tuple[int, ...] | None = None,
    ) -> list[HybridVectorHit]:
        self._validate_dense(dense)
        if not sparse or any(
            token_id < 0 or not isfinite(weight) or weight <= 0
            for token_id, weight in sparse.items()
        ):
            raise ValueError("sparse query must contain positive finite weights")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if document_id is not None and document_id <= 0:
            raise ValueError("document_id must be positive")
        if document_id is not None and document_ids is not None:
            raise ValueError("use document_id or document_ids, not both")
        expression: str | None
        if document_ids is not None:
            if len(document_ids) > 500 or any(value <= 0 for value in document_ids):
                raise ValueError("document_ids must contain at most 500 positive IDs")
            if not document_ids:
                return []
            safe_ids = sorted(set(document_ids))
            expression = f"document_id in [{', '.join(str(value) for value in safe_ids)}]"
        else:
            expression = f"document_id == {document_id}" if document_id is not None else None
        requests = [
            AnnSearchRequest(
                data=[list(dense)], anns_field="dense_vector",
                param={"metric_type": "COSINE", "params": {}},
                limit=limit, expr=expression,
            ),
            AnnSearchRequest(
                data=[sparse], anns_field="sparse_vector",
                param={"metric_type": "IP", "params": {}},
                limit=limit, expr=expression,
            ),
        ]
        result = self._client.hybrid_search(
            collection_name=self._collection, reqs=requests, ranker=RRFRanker(),
            limit=limit,
            output_fields=[
                "document_id", "chunk_id", "chunk_version", "page_start", "page_end",
                "model_name",
            ],
            consistency_level="Strong",
        )
        return [
            HybridVectorHit(
                vector_id=str(hit.get("id", hit.get("vector_id"))),
                document_id=int(hit["entity"]["document_id"]),
                chunk_id=int(hit["entity"]["chunk_id"]),
                chunk_version=int(hit["entity"]["chunk_version"]),
                page_start=int(hit["entity"]["page_start"]),
                page_end=int(hit["entity"]["page_end"]),
                model_name=str(hit["entity"]["model_name"]),
                score=float(hit["distance"]),
            )
            for hit in result[0]
        ]

    def delete(self, vector_id: str) -> None:
        if not vector_id:
            raise ValueError("vector_id must not be empty")
        self._client.delete(collection_name=self._collection, ids=[vector_id])

    def _validate_dense(self, dense: tuple[float, ...]) -> None:
        if len(dense) != self._dimension or not all(isfinite(value) for value in dense):
            raise ValueError(f"dense vector must contain {self._dimension} finite values")
