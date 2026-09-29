"""Contracts for versioned dense/sparse document retrieval."""

from dataclasses import dataclass
from math import isfinite
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class HybridChunkVector:
    vector_id: str
    document_id: int
    chunk_id: int
    chunk_version: int
    page_start: int
    page_end: int
    model_name: str
    dense: tuple[float, ...]
    sparse: dict[int, float]

    def __post_init__(self) -> None:
        if not self.vector_id or len(self.vector_id) > 100 or not self.model_name:
            raise ValueError("vector and model identities are required")
        if min(self.document_id, self.chunk_id, self.chunk_version, self.page_start) < 1:
            raise ValueError("document, chunk, version, and page IDs must be positive")
        if self.page_end < self.page_start:
            raise ValueError("invalid page range")
        if not self.dense or not all(isfinite(value) for value in self.dense):
            raise ValueError("dense vector must be non-empty and finite")
        if not self.sparse or any(
            token_id < 0 or not isfinite(weight) or weight <= 0
            for token_id, weight in self.sparse.items()
        ):
            raise ValueError("sparse vector must contain positive finite weights")


@dataclass(frozen=True, slots=True)
class HybridVectorHit:
    vector_id: str
    document_id: int
    chunk_id: int
    chunk_version: int
    page_start: int
    page_end: int
    model_name: str
    score: float


@runtime_checkable
class HybridVectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert(self, vector: HybridChunkVector) -> None: ...

    def search(
        self, dense: tuple[float, ...], sparse: dict[int, float], *,
        limit: int = 10, document_id: int | None = None,
        document_ids: tuple[int, ...] | None = None,
    ) -> list[HybridVectorHit]: ...

    def delete(self, vector_id: str) -> None: ...
