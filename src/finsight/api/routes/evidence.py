"""Versioned evidence search endpoint."""

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from finsight.api.knowledge_access import require_knowledge_access
from finsight.api.routes.auth import get_current_principal
from finsight.domain.access_control import Action
from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import EvidenceBundle
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_search import EvidenceSearchResult

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


class EvidenceSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=2000)
    company_code: str | None = Field(default=None, min_length=1, max_length=32)
    document_type: DocumentType | None = None
    report_year: int | None = Field(default=None, ge=1900, le=2100)
    knowledge_base_id: UUID


class RetrievalTraceResponse(BaseModel):
    model_name: str
    query_token_count: int | None
    filtered_document_ids: tuple[int, ...] | None
    candidate_vector_ids: tuple[str, ...]
    accepted_chunk_ids: tuple[int, ...]
    rejected_hit_count: int


class RerankingTraceResponse(BaseModel):
    input_count: int
    candidate_count: int
    scored_chunk_ids: tuple[int, ...]
    selected_chunk_ids: tuple[int, ...]
    duplicate_chunk_ids: tuple[int, ...]
    redundant_chunk_ids: tuple[int, ...]


class EvidenceSearchResponse(BaseModel):
    bundle: EvidenceBundle
    retrieval: RetrievalTraceResponse
    reranking: RerankingTraceResponse


class EvidenceSearchUseCase(Protocol):
    def search(
        self,
        query: str,
        *,
        criteria: DocumentSearchFilter | None = None,
    ) -> EvidenceSearchResult: ...


def get_evidence_search(request: Request) -> EvidenceSearchUseCase:
    service = getattr(request.app.state, "evidence_search", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="evidence search is not configured on this process",
        )
    return service


@router.post("/search", response_model=EvidenceSearchResponse)
def search_evidence(
    payload: EvidenceSearchRequest,
    request: Request,
    service: Annotated[EvidenceSearchUseCase, Depends(get_evidence_search)],
) -> EvidenceSearchResponse:
    principal = get_current_principal(request)
    require_knowledge_access(request, principal, payload.knowledge_base_id, Action.KNOWLEDGE_READ)
    try:
        result = service.search(
            payload.query,
            criteria=DocumentSearchFilter(
                company_code=payload.company_code,
                document_type=payload.document_type,
                report_year=payload.report_year,
                knowledge_base_id=payload.knowledge_base_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return EvidenceSearchResponse(
        bundle=result.bundle,
        retrieval=RetrievalTraceResponse(
            model_name=result.retrieval_trace.model_name,
            query_token_count=result.retrieval_trace.query_token_count,
            filtered_document_ids=result.retrieval_trace.filtered_document_ids,
            candidate_vector_ids=result.retrieval_trace.candidate_vector_ids,
            accepted_chunk_ids=result.retrieval_trace.accepted_chunk_ids,
            rejected_hit_count=len(result.retrieval_trace.rejected_hits),
        ),
        reranking=RerankingTraceResponse.model_validate(
            result.reranking_trace,
            from_attributes=True,
        ),
    )
