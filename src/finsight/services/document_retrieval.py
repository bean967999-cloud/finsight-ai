"""Filtered hybrid retrieval with authoritative Chunk readback and trace."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.domain.document_chunking import ChunkDraft, ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType
from finsight.domain.embedding import EmbeddingProvider, EmbeddingSpec
from finsight.infrastructure.database.models import Document, DocumentChunk
from finsight.services.document_search_filter import DocumentFilterResolver, DocumentSearchFilter
from finsight.services.hybrid_vector_store import HybridVectorHit, HybridVectorStore

SessionProvider = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    vector_id: str
    document_id: int
    chunk_id: int
    parse_job_id: int
    chunk_version: int
    kind: ChunkKind
    content: str
    page_start: int
    page_end: int
    section_path: tuple[str, ...]
    source_blocks: tuple[SourceBlockRef, ...]
    document_title: str
    document_type: DocumentType
    company_code: str | None
    report_year: int | None
    source_url: str | None
    score: float


@dataclass(frozen=True, slots=True)
class RejectedHit:
    vector_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    model_name: str
    query_token_count: int | None
    filtered_document_ids: tuple[int, ...] | None
    candidate_vector_ids: tuple[str, ...]
    accepted_chunk_ids: tuple[int, ...]
    rejected_hits: tuple[RejectedHit, ...]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunks: tuple[RetrievedChunk, ...]
    trace: RetrievalTrace


class DocumentRetrievalService:
    def __init__(
        self,
        session_provider: SessionProvider,
        embeddings: EmbeddingProvider,
        vectors: HybridVectorStore,
        *,
        spec: EmbeddingSpec | None = None,
        filters: DocumentFilterResolver | None = None,
    ) -> None:
        self._sessions = session_provider
        self._embeddings = embeddings
        self._vectors = vectors
        self._spec = spec or EmbeddingSpec()
        self._filters = filters or DocumentFilterResolver(session_provider)

    def retrieve(
        self, query: str, *, criteria: DocumentSearchFilter | None = None, limit: int = 5,
    ) -> RetrievalResult:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        criteria = criteria or DocumentSearchFilter()
        document_ids = self._filters.resolve(criteria)
        if document_ids == ():
            return RetrievalResult((), RetrievalTrace(self._spec.model_name, None, (), (), (), ()))

        embedded = self._embeddings.encode_query(query.strip())
        embedded.validate(self._spec)
        candidates = self._vectors.search(
            embedded.dense, embedded.sparse,
            limit=min(100, limit * 3), document_ids=document_ids,
        )
        # A vector backend can return off-scope hits despite prefiltering.
        # Do not read their chunks or expose their IDs/counts in the trace.
        if document_ids is not None:
            allowed_ids = set(document_ids)
            candidates = [hit for hit in candidates if hit.document_id in allowed_ids]
        candidate_ids = tuple(dict.fromkeys(hit.chunk_id for hit in candidates))
        with self._sessions() as session:
            statement = (
                select(DocumentChunk, Document)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(DocumentChunk.id.in_(candidate_ids))
            )
            if document_ids is not None:
                statement = statement.where(DocumentChunk.document_id.in_(document_ids))
            rows = {
                row.id: (row, document)
                for row, document in session.execute(statement)
            }
        accepted: list[RetrievedChunk] = []
        rejected: list[RejectedHit] = []
        seen_ids: set[int] = set()
        for hit in candidates:
            trace_id = hit.vector_id if document_ids is None else "[redacted]"
            if hit.chunk_id in seen_ids:
                rejected.append(RejectedHit(trace_id, "duplicate chunk candidate"))
                continue
            seen_ids.add(hit.chunk_id)
            pair = rows.get(hit.chunk_id)
            if pair is None:
                reason = (
                    "document is outside selected filter set"
                    if document_ids is not None and hit.document_id not in document_ids
                    else "chunk missing from PostgreSQL"
                )
                rejected.append(RejectedHit(trace_id, reason))
                continue
            row, document = pair
            draft, reason = self._verify(row, document, hit, embedded.model_name, criteria, document_ids)
            if draft is None:
                rejected.append(RejectedHit(trace_id, reason))
                continue
            accepted.append(RetrievedChunk(
                vector_id=hit.vector_id,
                document_id=row.document_id,
                chunk_id=row.id,
                parse_job_id=draft.parse_job_id,
                chunk_version=row.chunk_version,
                kind=draft.kind,
                content=draft.content,
                page_start=draft.page_start,
                page_end=draft.page_end,
                section_path=draft.section_path,
                source_blocks=draft.source_blocks,
                document_title=document.title,
                document_type=document.document_type,
                company_code=document.company_code,
                report_year=document.report_year,
                source_url=document.source_url,
                score=hit.score,
            ))
            if len(accepted) == limit:
                break
        return RetrievalResult(
            chunks=tuple(accepted),
            trace=RetrievalTrace(
                model_name=embedded.model_name,
                query_token_count=embedded.token_count,
                filtered_document_ids=document_ids,
                candidate_vector_ids=(
                    tuple(chunk.vector_id for chunk in accepted)
                    if document_ids is not None
                    else tuple(hit.vector_id for hit in candidates)
                ),
                accepted_chunk_ids=tuple(chunk.chunk_id for chunk in accepted),
                rejected_hits=tuple(rejected),
            ),
        )

    @staticmethod
    def _verify(
        row: DocumentChunk,
        document: Document,
        hit: HybridVectorHit,
        model_name: str,
        criteria: DocumentSearchFilter,
        document_ids: tuple[int, ...] | None,
    ) -> tuple[ChunkDraft | None, str]:
        if (
            row.vector_id != hit.vector_id
            or row.document_id != hit.document_id
            or row.chunk_version != hit.chunk_version
            or row.page_start != hit.page_start
            or row.page_end != hit.page_end
            or hit.model_name != model_name
            or not isfinite(hit.score)
        ):
            return None, "vector identity, version, model, page, or score mismatch"
        if document_ids is not None and document.id not in document_ids:
            return None, "document is outside selected filter set"
        if (
            (criteria.company_code is not None and document.company_code != criteria.company_code)
            or (criteria.document_type is not None and document.document_type != criteria.document_type)
            or (criteria.report_year is not None and document.report_year != criteria.report_year)
        ):
            return None, "document metadata changed after prefilter"
        try:
            draft = ChunkDraft.model_validate({
                "document_id": row.document_id,
                "parse_job_id": row.parse_job_id,
                "chunk_index": row.chunk_index,
                "chunk_version": row.chunk_version,
                "kind": row.kind,
                "content": row.content,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "section_path": row.section_path,
                "source_blocks": row.source_blocks,
                "table_format": row.table_format,
                "asset_path": row.asset_path,
            })
        except ValidationError:
            return None, "chunk payload or source coordinates are invalid"
        if draft.content_sha256 != row.content_sha256:
            return None, "chunk content digest mismatch"
        return draft, ""
