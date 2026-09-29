"""Adapters to existing services; raw outputs remain pending later evidence review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from finsight.domain.query_plan import PlanStatus, StructuredQueryPlan
from finsight.domain.research_flow import (
    ResearchPlanItem,
    ResearchTool,
    ResearchToolResult,
    ToolStatus,
)
from finsight.domain.schemas import RiskMetrics
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evidence_search import EvidenceSearchResult
from finsight.services.query_planning import query_digest
from finsight.services.risk_engine import RiskEngine
from finsight.services.structured_query import StructuredQueryOutcome


class DocumentSearchPort(Protocol):
    def search(self, query: str, *, criteria=None) -> EvidenceSearchResult: ...


class StructuredQueryPort(Protocol):
    def execute(self, plan: StructuredQueryPlan) -> StructuredQueryOutcome: ...


class RiskCalculationPort(Protocol):
    def analyze(self, prices: list[float]) -> RiskMetrics: ...


ToolOutput = EvidenceSearchResult | StructuredQueryOutcome | RiskMetrics


@dataclass(frozen=True, slots=True)
class ToolExecution:
    result: ResearchToolResult
    output: ToolOutput | None = None


class ResearchToolAdapter:
    def __init__(
        self,
        *,
        document_search: DocumentSearchPort | None = None,
        structured_query: StructuredQueryPort | None = None,
        risk_calculation: RiskCalculationPort | None = None,
        document_answer=None,
    ) -> None:
        self._document_search = document_search
        self._document_answer = document_answer
        self._structured_query = structured_query
        self._risk_calculation = risk_calculation or RiskEngine()

    def execute(
        self,
        item: ResearchPlanItem,
        *,
        query: str,
        prices: tuple[float, ...] | None = None,
        structured_plan: StructuredQueryPlan | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> ToolExecution:
        if item.tool == ResearchTool.DOCUMENT_SEARCH:
            return self.search_documents(query, knowledge_base_id=knowledge_base_id)
        if item.tool == ResearchTool.STRUCTURED_QUERY:
            return self.query_data(query, structured_plan)
        if item.tool == ResearchTool.RISK_CALCULATION:
            return self.calculate_risk(prices)
        raise ValueError(f"unsupported research tool: {item.tool}")

    def search_documents(
        self, query: str, *, knowledge_base_id: UUID | None = None
    ) -> ToolExecution:
        tool = ResearchTool.DOCUMENT_SEARCH
        if knowledge_base_id is None:
            return self._unavailable(tool, "KnowledgeBaseScopeRequired")
        if self._document_search is None:
            return self._unavailable(tool, "DocumentSearchNotConfigured")
        try:
            if self._document_answer is not None:
                grounded = self._document_answer.answer(query, knowledge_base_id)
                if grounded is not None:
                    return ToolExecution(ResearchToolResult(
                        tool=tool, status=ToolStatus.SUCCEEDED, document_answer=grounded,
                    ))
            output = self._document_search.search(
                query, criteria=DocumentSearchFilter(knowledge_base_id=knowledge_base_id)
            )
        except (ConnectionError, TimeoutError):
            return self._unavailable(tool, "DocumentSearchUnavailable")
        except ValueError:
            return self._failed(tool, "InvalidDocumentQuery")
        # Citations are pending until verified against authoritative source data.
        return ToolExecution(ResearchToolResult(tool=tool, status=ToolStatus.SUCCEEDED), output)

    def query_data(self, query: str, plan: StructuredQueryPlan | None) -> ToolExecution:
        tool = ResearchTool.STRUCTURED_QUERY
        if plan is None or plan.status != PlanStatus.READY:
            return self._unavailable(tool, "StructuredPlanRequired")
        if plan.query_sha256 != query_digest(query):
            return self._failed(tool, "QueryPlanMismatch")
        if self._structured_query is None:
            return self._unavailable(tool, "StructuredQueryNotConfigured")
        try:
            output = self._structured_query.execute(plan)
        except (ConnectionError, TimeoutError):
            return self._unavailable(tool, "StructuredQueryUnavailable")
        except ValueError:
            return self._failed(tool, "InvalidStructuredQuery")
        # Raw rows need entity, period, metric and unit checks before normalization.
        return ToolExecution(ResearchToolResult(tool=tool, status=ToolStatus.SUCCEEDED), output)

    def calculate_risk(self, prices: tuple[float, ...] | None) -> ToolExecution:
        tool = ResearchTool.RISK_CALCULATION
        if prices is None:
            return self._unavailable(tool, "PricesRequired")
        try:
            output = self._risk_calculation.analyze(list(prices))
        except ValueError:
            return self._failed(tool, "InvalidPriceSeries")
        # Plain prices have no dates, instrument or source; metrics are not provenance evidence.
        return ToolExecution(ResearchToolResult(tool=tool, status=ToolStatus.SUCCEEDED), output)

    @staticmethod
    def _unavailable(tool: ResearchTool, code: str) -> ToolExecution:
        return ToolExecution(
            ResearchToolResult(tool=tool, status=ToolStatus.UNAVAILABLE, error_code=code)
        )

    @staticmethod
    def _failed(tool: ResearchTool, code: str) -> ToolExecution:
        return ToolExecution(ResearchToolResult(tool=tool, status=ToolStatus.FAILED, error_code=code))
