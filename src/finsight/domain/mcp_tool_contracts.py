"""Transport-independent contracts for the four financial MCP tools."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.access_control import Action, Principal, ResourceScope, evaluate_access
from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import CitationStatus
from finsight.domain.financial_data import ReportingPeriodType, StatementType
from finsight.domain.query_plan import (
    ComparisonType,
    EntitySelection,
    MetricRequest,
    QueryIntent,
    QueryOrder,
    TimeSelection,
)
from finsight.domain.research_flow import AnswerStatus
from finsight.domain.schemas import RiskMetrics


class ToolName(StrEnum):
    SEARCH_FINANCIAL_DOCUMENTS = "search_financial_documents"
    QUERY_FINANCIAL_DATA = "query_financial_data"
    CALCULATE_PORTFOLIO_RISK = "calculate_portfolio_risk"
    GENERATE_RESEARCH_BRIEF = "generate_research_brief"


class ToolErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    ACCESS_DENIED = "access_denied"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INTERNAL_ERROR = "internal_error"


class ToolFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ToolErrorCode
    message: str = Field(min_length=1, max_length=200)


class ToolCallContext(BaseModel):
    """Server-resolved identity; deliberately separate from client-controlled tool inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: Principal
    request_id: UUID


class SearchFinancialDocumentsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    workspace_id: UUID
    knowledge_base_id: UUID
    query: str = Field(min_length=2, max_length=2000)
    company_code: str | None = Field(default=None, min_length=1, max_length=32)
    document_type: DocumentType | None = None
    report_year: int | None = Field(default=None, ge=1900, le=2100)


class DocumentReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    document_title: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=2000)
    excerpt_truncated: bool = False
    citation_status: CitationStatus

    @model_validator(mode="after")
    def valid_page_range(self) -> DocumentReference:
        if self.page_end < self.page_start:
            raise ValueError("page range is reversed")
        return self


class SearchFinancialDocumentsOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    references: tuple[DocumentReference, ...] = Field(max_length=20)
    candidate_count: int = Field(ge=0)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitations: tuple[str, ...] = ()


class QueryFinancialDataInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    workspace_id: UUID
    query: str = Field(min_length=2, max_length=2000)
    intent: QueryIntent
    entities: EntitySelection = EntitySelection()
    metrics: tuple[MetricRequest, ...] = ()
    time: TimeSelection = TimeSelection()
    period_type: ReportingPeriodType | None = None
    statement_type: StatementType | None = None
    comparison: ComparisonType = ComparisonType.NONE
    order_by: tuple[QueryOrder, ...] = ()
    limit: int = Field(default=100, ge=1, le=100)


class QueryFinancialDataOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    columns: tuple[str, ...]
    rows: tuple[dict[str, str | int | float | bool | None], ...] = Field(max_length=100)
    row_count: int = Field(ge=0)
    sql_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent_rows(self) -> QueryFinancialDataOutput:
        if self.row_count != len(self.rows):
            raise ValueError("row count does not match returned rows")
        if any(set(row) != set(self.columns) for row in self.rows):
            raise ValueError("row columns do not match declared columns")
        if any(
            isinstance(value, float) and not isfinite(value)
            for row in self.rows for value in row.values()
        ):
            raise ValueError("row values must be finite")
        return self


class CalculatePortfolioRiskInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    prices: tuple[float, ...] = Field(min_length=3, max_length=10000)
    confidence: float = Field(default=0.95, gt=0.5, lt=1)
    trading_days: int = Field(default=252, ge=1, le=366)
    risk_free_rate: float = 0.0

    @model_validator(mode="after")
    def finite_inputs(self) -> CalculatePortfolioRiskInput:
        if any(not isfinite(price) or price <= 0 for price in self.prices):
            raise ValueError("prices must be finite positive values")
        if not isfinite(self.confidence) or not isfinite(self.risk_free_rate):
            raise ValueError("risk parameters must be finite")
        return self


class CalculatePortfolioRiskOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: RiskMetrics
    source: str = "caller_supplied_prices"
    limitations: tuple[str, ...] = (
        "Price dates and data source are not independently verified.",
    )

    @model_validator(mode="after")
    def finite_metrics(self) -> CalculatePortfolioRiskOutput:
        values = self.metrics.model_dump().values()
        if any(isinstance(value, float) and not isfinite(value) for value in values):
            raise ValueError("risk metrics must be finite")
        return self


class GenerateResearchBriefInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    workspace_id: UUID
    query: str = Field(min_length=2, max_length=2000)
    knowledge_base_id: UUID | None = None
    prices: tuple[float, ...] | None = Field(default=None, min_length=3, max_length=10000)
    release_requested: bool = False

    @model_validator(mode="after")
    def finite_prices(self) -> GenerateResearchBriefInput:
        if self.prices is not None and any(
            not isfinite(price) or price <= 0 for price in self.prices
        ):
            raise ValueError("prices must be finite positive values")
        return self


class GenerateResearchBriefOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer_status: AnswerStatus
    answer: str | None = Field(default=None, max_length=10000)
    limitations: tuple[str, ...] = ()
    review_pending: bool = False
    thread_id: UUID | None = None

    @model_validator(mode="after")
    def pending_is_not_released(self) -> GenerateResearchBriefOutput:
        if self.review_pending and (self.answer is not None or self.thread_id is None):
            raise ValueError("pending review needs a thread and cannot release an answer")
        if not self.review_pending and self.answer is None:
            raise ValueError("completed brief needs an answer or explicit non-answer")
        if self.answer_status != AnswerStatus.ANSWERED and not self.limitations:
            raise ValueError("non-answer needs an explicit limitation")
        return self


TOOL_ACTIONS: dict[ToolName, Action] = {
    ToolName.SEARCH_FINANCIAL_DOCUMENTS: Action.KNOWLEDGE_READ,
    ToolName.QUERY_FINANCIAL_DATA: Action.RESEARCH_SUBMIT,
    ToolName.CALCULATE_PORTFOLIO_RISK: Action.RESEARCH_SUBMIT,
    ToolName.GENERATE_RESEARCH_BRIEF: Action.RESEARCH_SUBMIT,
}


def tool_access_allowed(
    context: ToolCallContext, name: ToolName, *, workspace_id: UUID,
    knowledge_base_id: UUID | None = None, release_requested: bool = False,
) -> bool:
    """Permission check only; adapters must also verify knowledge-base ownership."""
    scope = ResourceScope(workspace_id=workspace_id, knowledge_base_id=knowledge_base_id)
    if not evaluate_access(context.principal, TOOL_ACTIONS[name], scope).allowed:
        return False
    return not release_requested or (
        name == ToolName.GENERATE_RESEARCH_BRIEF
        and evaluate_access(context.principal, Action.RELEASE_REQUEST, scope).allowed
    )
