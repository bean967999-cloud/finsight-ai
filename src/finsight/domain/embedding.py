"""Model-neutral contracts for document and query representations."""

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    model_name: str = "BAAI/bge-m3"
    dimension: int = 1024
    model_max_tokens: int = 8192
    batch_max_tokens: int = 4096
    query_max_tokens: int = 512

    def __post_init__(self) -> None:
        if not self.model_name or self.dimension < 1:
            raise ValueError("model identity and positive dimension are required")
        if not 1 <= self.batch_max_tokens <= self.model_max_tokens:
            raise ValueError("batch token limit must fit the model context")
        if not 1 <= self.query_max_tokens <= self.batch_max_tokens:
            raise ValueError("query token limit must fit the batch limit")

    def validate_tokens(self, token_count: int) -> None:
        if token_count < 1 or token_count > self.batch_max_tokens:
            raise ValueError("input token count is empty or exceeds configured limit")


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    chunk_id: int
    document_id: int
    chunk_version: int
    content_sha256: str
    text: str

    def __post_init__(self) -> None:
        if min(self.chunk_id, self.document_id, self.chunk_version) < 1:
            raise ValueError("chunk, document, and version IDs must be positive")
        if len(self.content_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        if not self.text.strip():
            raise ValueError("embedding input must not be empty")
        if sha256(self.text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("embedding input text does not match content_sha256")


@dataclass(frozen=True, slots=True)
class EmbeddingOutput:
    chunk_id: int
    model_name: str
    token_count: int
    dense: tuple[float, ...]
    sparse: dict[int, float]

    def validate(self, spec: EmbeddingSpec) -> None:
        if self.chunk_id < 1:
            raise ValueError("document embedding must reference a positive chunk ID")
        _validate_vectors(spec, self.model_name, self.token_count, self.dense, self.sparse)


@dataclass(frozen=True, slots=True)
class QueryEmbedding:
    model_name: str
    token_count: int
    dense: tuple[float, ...]
    sparse: dict[int, float]

    def validate(self, spec: EmbeddingSpec) -> None:
        _validate_vectors(spec, self.model_name, self.token_count, self.dense, self.sparse)
        if self.token_count > spec.query_max_tokens:
            raise ValueError("query exceeds configured token limit")


def _validate_vectors(
    spec: EmbeddingSpec, model_name: str, token_count: int,
    dense: tuple[float, ...], sparse: dict[int, float],
) -> None:
    if model_name != spec.model_name:
        raise ValueError("embedding model does not match the specification")
    spec.validate_tokens(token_count)
    if len(dense) != spec.dimension or not all(isfinite(value) for value in dense):
        raise ValueError("dense vector has wrong dimension or non-finite values")
    if not sparse or any(
        token_id < 0 or not isfinite(weight) or weight <= 0
        for token_id, weight in sparse.items()
    ):
        raise ValueError("sparse vector must contain positive finite token weights")


@runtime_checkable
class EmbeddingProvider(Protocol):
    def count_tokens(self, text: str) -> int: ...

    def encode_documents(self, inputs: tuple[EmbeddingInput, ...]) -> tuple[EmbeddingOutput, ...]: ...

    def encode_query(self, query: str) -> QueryEmbedding: ...
