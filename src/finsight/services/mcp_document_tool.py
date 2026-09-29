"""Authorized document-search tool over the existing evidence pipeline."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from finsight.domain.evidence import CitationStatus
from finsight.domain.mcp_tool_contracts import (
    DocumentReference,
    SearchFinancialDocumentsInput,
    SearchFinancialDocumentsOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
    ToolName,
    tool_access_allowed,
)
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_search import EvidenceSearchResult
from finsight.services.mcp_tool_audit import ToolAudit

_ROUTE = "/mcp/tools/search_financial_documents"
_MAX_REFERENCES = 20
_MAX_EXCERPT_LENGTH = 2000


class KnowledgeOwnership(Protocol):
    def workspace_for(self, knowledge_base_id: UUID) -> UUID | None: ...


class EvidenceSearch(Protocol):
    def search(
        self, query: str, *, criteria: DocumentSearchFilter | None = None,
    ) -> EvidenceSearchResult: ...


class FinancialDocumentTool:
    def __init__(
        self, audit: ToolAudit, ownership: KnowledgeOwnership, search: EvidenceSearch,
    ) -> None:
        self._audit = audit
        self._ownership = ownership
        self._search = search

    def execute(
        self, context: ToolCallContext, payload: SearchFinancialDocumentsInput,
    ) -> SearchFinancialDocumentsOutput | ToolFailure:
        try:
            self._audit.begin(
                context.request_id, action=ToolName.SEARCH_FINANCIAL_DOCUMENTS.value,
                method="MCP", route_pattern=_ROUTE, target_id=None,
            )
        except Exception:  # noqa: BLE001 - no document access without audit
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")

        status_code = 500
        outcome: SearchFinancialDocumentsOutput | ToolFailure
        try:
            if not tool_access_allowed(  # noqa: SIM114 - check grants before ownership lookup
                context, ToolName.SEARCH_FINANCIAL_DOCUMENTS,
                workspace_id=payload.workspace_id,
                knowledge_base_id=payload.knowledge_base_id,
            ):
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            elif self._ownership.workspace_for(payload.knowledge_base_id) != payload.workspace_id:
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            else:
                result = self._search.search(
                    payload.query,
                    criteria=DocumentSearchFilter(
                        company_code=payload.company_code,
                        document_type=payload.document_type,
                        report_year=payload.report_year,
                        knowledge_base_id=payload.knowledge_base_id,
                    ),
                )
                citations = result.bundle.citations
                references = tuple(
                    DocumentReference(
                        document_id=item.evidence.candidate.document_id,
                        chunk_id=item.evidence.candidate.chunk_id,
                        page_start=item.evidence.candidate.page_start,
                        page_end=item.evidence.candidate.page_end,
                        document_title=item.evidence.candidate.document_title,
                        excerpt=item.quoted_text[:_MAX_EXCERPT_LENGTH],
                        excerpt_truncated=len(item.quoted_text) > _MAX_EXCERPT_LENGTH,
                        citation_status=item.status,
                    )
                    for item in citations[:_MAX_REFERENCES]
                )
                limitations = []
                if not references:
                    limitations.append("No evidence found in the authorized knowledge base.")
                if any(item.citation_status != CitationStatus.VERIFIED for item in references):
                    limitations.append("Retrieved excerpts are not verified financial claims.")
                if len(citations) > _MAX_REFERENCES:
                    limitations.append("Additional references were omitted by the output limit.")
                outcome = SearchFinancialDocumentsOutput(
                    references=references, candidate_count=result.bundle.candidate_count,
                    query_sha256=result.bundle.query_sha256, limitations=tuple(limitations),
                )
                status_code = 200
        except (ValueError, ValidationError):
            status_code = 422
            outcome = ToolFailure(code=ToolErrorCode.INVALID_INPUT, message="Invalid document search")
        except Exception:  # noqa: BLE001 - hide document and retrieval internals
            status_code = 503
            outcome = ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Document source unavailable")

        try:
            self._audit.finish(
                context.request_id, status_code=status_code,
                actor_user_id=context.principal.user_id, workspace_id=payload.workspace_id,
                knowledge_base_id=payload.knowledge_base_id,
            )
        except Exception:  # noqa: BLE001 - never release excerpts without completed audit
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")
        return outcome
