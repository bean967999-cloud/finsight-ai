"""Storage-neutral vector contract for document chunks."""

from dataclasses import dataclass
from math import isfinite
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ChunkVector:
    vector_id: str
    document_id: int
    chunk_id: int
    page_start: int
    page_end: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.vector_id or len(self.vector_id) > 100:
            raise ValueError("vector_id must be 1-100 characters")
        if self.document_id <= 0 or self.chunk_id <= 0:
            raise ValueError("document_id and chunk_id must be positive")
        if self.page_start <= 0 or self.page_end < self.page_start:
            raise ValueError("invalid page range")
        if not self.values or not all(isfinite(value) for value in self.values):
            raise ValueError("vector values must be non-empty and finite")


@dataclass(frozen=True, slots=True)
class VectorHit:
    vector_id: str
    document_id: int
    chunk_id: int
    page_start: int
    page_end: int
    score: float


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert(self, vector: ChunkVector) -> None: ...

    def search(
        self, values: tuple[float, ...], *, limit: int = 10, document_id: int | None = None
    ) -> list[VectorHit]: ...

    def delete(self, vector_id: str) -> None: ...
