"""Retryable bridge from persisted chunks to Milvus hybrid vectors."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.domain.embedding import EmbeddingInput, EmbeddingProvider, EmbeddingSpec
from finsight.infrastructure.database.models import DocumentChunk
from finsight.services.hybrid_vector_store import HybridChunkVector, HybridVectorStore

SessionProvider = Callable[[], Session]


class ChunkIndexingError(RuntimeError):
    """Saved chunks cannot be safely linked to generated vectors."""


@dataclass(frozen=True, slots=True)
class ChunkIndexingResult:
    parse_job_id: int
    chunk_version: int
    vector_ids: tuple[str, ...]


class DocumentChunkIndexingService:
    def __init__(
        self,
        session_provider: SessionProvider,
        embeddings: EmbeddingProvider,
        vectors: HybridVectorStore,
        *,
        spec: EmbeddingSpec | None = None,
        batch_size: int = 2,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._sessions = session_provider
        self._embeddings = embeddings
        self._vectors = vectors
        self._spec = spec or EmbeddingSpec()
        self._batch_size = batch_size

    def index_parse_job(self, parse_job_id: int, *, chunk_version: int = 1) -> ChunkIndexingResult:
        if parse_job_id < 1 or chunk_version < 1:
            raise ValueError("parse_job_id and chunk_version must be positive")
        with self._sessions() as session:
            rows = list(session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.parse_job_id == parse_job_id,
                    DocumentChunk.chunk_version == chunk_version,
                )
                .order_by(DocumentChunk.chunk_index)
            ))
            if not rows or [row.chunk_index for row in rows] != list(range(len(rows))):
                raise ChunkIndexingError("saved chunk batch is empty or incomplete")
            items = tuple(
                EmbeddingInput(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    chunk_version=row.chunk_version,
                    content_sha256=row.content_sha256,
                    text=row.content or "",
                )
                for row in rows
            )
            metadata = tuple(
                (row.id, row.document_id, row.chunk_version, row.page_start, row.page_end,
                 row.content_sha256, row.vector_id)
                for row in rows
            )
        vector_ids = tuple(self._vector_id(item) for item in items)
        for (_, _, _, _, _, _, existing), vector_id in zip(metadata, vector_ids, strict=True):
            if existing is not None and existing != vector_id:
                raise ChunkIndexingError("chunk is linked to a different vector identity")
        # Validate the complete batch before the first external write.
        for item in items:
            self._spec.validate_tokens(self._embeddings.count_tokens(item.text))
        self._vectors.ensure_collection()
        for start in range(0, len(items), self._batch_size):
            batch = items[start:start + self._batch_size]
            outputs = self._embeddings.encode_documents(batch)
            if len(outputs) != len(batch):
                raise ChunkIndexingError("embedding provider returned an incomplete batch")
            for item, output, info, vector_id in zip(
                batch, outputs, metadata[start:start + self._batch_size],
                vector_ids[start:start + self._batch_size], strict=True,
            ):
                output.validate(self._spec)
                if output.chunk_id != item.chunk_id:
                    raise ChunkIndexingError("embedding output does not match input chunk")
                row_id, document_id, version, page_start, page_end, digest, _ = info
                self._vectors.upsert(HybridChunkVector(
                    vector_id=vector_id,
                    document_id=document_id,
                    chunk_id=row_id,
                    chunk_version=version,
                    page_start=page_start,
                    page_end=page_end,
                    model_name=output.model_name,
                    dense=output.dense,
                    sparse=output.sparse,
                ))
                # PostgreSQL link follows Milvus upsert. A failed link leaves an
                # unreferenced, harmless vector that a retry can overwrite.
                with self._sessions() as session, session.begin():
                    current = session.scalar(
                        select(DocumentChunk).where(DocumentChunk.id == row_id).with_for_update()
                    )
                    if (
                        current is None
                        or current.content_sha256 != digest
                        or current.chunk_version != version
                        or current.parse_job_id != parse_job_id
                        or current.vector_id not in (None, vector_id)
                    ):
                        raise ChunkIndexingError("chunk changed while indexing")
                    current.vector_id = vector_id
        return ChunkIndexingResult(parse_job_id, chunk_version, vector_ids)

    def _vector_id(self, item: EmbeddingInput) -> str:
        identity = f"{self._spec.model_name}:{item.content_sha256}"
        fingerprint = sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"chunk-{item.chunk_id}-v{item.chunk_version}-{fingerprint}"
