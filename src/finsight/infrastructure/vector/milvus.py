"""Milvus adapter for document-chunk dense vectors."""

from math import isfinite
from typing import Any

from pymilvus import DataType, MilvusClient  # type: ignore[import-untyped]

from finsight.services.vector_store import ChunkVector, VectorHit


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        *,
        collection_name: str = "finsight_document_chunks_v1",
        dimension: int = 1024,
        client: Any | None = None,
    ) -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        if not collection_name or not collection_name.replace("_", "").isalnum():
            raise ValueError("collection_name must be alphanumeric or underscores")
        self._client = client if client is not None else MilvusClient(uri=uri)
        self._collection = collection_name
        self._dimension = dimension

    def ensure_collection(self) -> None:
        if self._client.has_collection(collection_name=self._collection):
            return
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("vector_id", DataType.VARCHAR, is_primary=True, max_length=100)
        schema.add_field("document_id", DataType.INT64)
        schema.add_field("chunk_id", DataType.INT64)
        schema.add_field("page_start", DataType.INT64)
        schema.add_field("page_end", DataType.INT64)
        schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=self._dimension)
        indexes = self._client.prepare_index_params()
        indexes.add_index(
            field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        self._client.create_collection(
            collection_name=self._collection, schema=schema, index_params=indexes
        )

    def upsert(self, vector: ChunkVector) -> None:
        self._validate_values(vector.values)
        self._client.upsert(
            collection_name=self._collection,
            data={
                "vector_id": vector.vector_id,
                "document_id": vector.document_id,
                "chunk_id": vector.chunk_id,
                "page_start": vector.page_start,
                "page_end": vector.page_end,
                "dense_vector": list(vector.values),
            },
        )

    def search(
        self, values: tuple[float, ...], *, limit: int = 10, document_id: int | None = None
    ) -> list[VectorHit]:
        self._validate_values(values)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if document_id is not None and document_id <= 0:
            raise ValueError("document_id must be positive")
        result = self._client.search(
            collection_name=self._collection,
            data=[list(values)],
            limit=limit,
            filter=f"document_id == {document_id}" if document_id is not None else "",
            output_fields=["document_id", "chunk_id", "page_start", "page_end"],
            consistency_level="Strong",
        )
        return [
            VectorHit(
                vector_id=str(hit["vector_id"]),
                document_id=int(hit["entity"]["document_id"]),
                chunk_id=int(hit["entity"]["chunk_id"]),
                page_start=int(hit["entity"]["page_start"]),
                page_end=int(hit["entity"]["page_end"]),
                score=float(hit["distance"]),
            )
            for hit in result[0]
        ]

    def delete(self, vector_id: str) -> None:
        if not vector_id:
            raise ValueError("vector_id must not be empty")
        self._client.delete(collection_name=self._collection, ids=[vector_id])

    def _validate_values(self, values: tuple[float, ...]) -> None:
        if len(values) != self._dimension or not all(isfinite(value) for value in values):
            raise ValueError(f"vector must contain {self._dimension} finite values")
