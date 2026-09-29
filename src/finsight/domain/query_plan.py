"""Structured, reviewable plans between a user question and SQL generation."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finsight.domain.financial_data import ReportingPeriodType, StatementType


class QueryIntent(StrEnum):
    COMPANY_LOOKUP = "company_lookup"
    FINANCIAL_STATEMENT = "financial_statement"
    FINANCIAL_INDICATOR = "financial_indicator"
    MARKET_PRICE = "market_price"


class PlanStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"


class ComparisonType(StrEnum):
    NONE = "none"
    TREND = "trend"
    YEAR_OVER_YEAR = "year_over_year"


class AggregationType(StrEnum):
    NONE = "none"
    SUM = "sum"
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class SortDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class EntitySelection(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    company_codes: tuple[str, ...] = ()
    company_names: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()

    @field_validator("company_codes", "tickers", "exchanges", mode="after")
    @classmethod
    def normalize_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.upper() for value in values)
        if any(not value for value in normalized):
            raise ValueError("entity codes must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("entity codes must be unique")
        return normalized

    @field_validator("company_names", mode="after")
    @classmethod
    def validate_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("company names must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("company names must be unique")
        return values

    @property
    def is_empty(self) -> bool:
        return not any((self.company_codes, self.company_names, self.tickers))


class TimeSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_years: tuple[int, ...] = ()
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_time(self) -> "TimeSelection":
        if len(self.report_years) != len(set(self.report_years)):
            raise ValueError("report_years must be unique")
        if self.report_years != tuple(sorted(self.report_years)):
            raise ValueError("report_years must be ordered ascending")
        if any(year < 1900 or year > 2100 for year in self.report_years):
            raise ValueError("report_years must be between 1900 and 2100")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must not be before start_date")
        if self.report_years and self.start_date is not None:
            raise ValueError("use report_years or a date range, not both")
        return self

    @property
    def is_empty(self) -> bool:
        return not self.report_years and self.start_date is None


class MetricRequest(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=100)
    aggregation: AggregationType = AggregationType.NONE


class QueryOrder(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    field: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    direction: SortDirection = SortDirection.ASCENDING


class StructuredQueryPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: PlanStatus
    intent: QueryIntent
    entities: EntitySelection = EntitySelection()
    metrics: tuple[MetricRequest, ...] = ()
    time: TimeSelection = TimeSelection()
    period_type: ReportingPeriodType | None = None
    statement_type: StatementType | None = None
    comparison: ComparisonType = ComparisonType.NONE
    order_by: tuple[QueryOrder, ...] = ()
    limit: int = Field(default=100, ge=1, le=500)
    clarification_questions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> "StructuredQueryPlan":
        metric_keys = [(item.term.casefold(), item.aggregation) for item in self.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("metric requests must be unique")
        order_fields = [item.field for item in self.order_by]
        if len(order_fields) != len(set(order_fields)):
            raise ValueError("order_by fields must be unique")
        if any(not question.strip() for question in self.clarification_questions):
            raise ValueError("clarification questions must not be empty")
        if self.status == PlanStatus.NEEDS_CLARIFICATION:
            if not self.clarification_questions:
                raise ValueError("clarification plan requires at least one question")
            return self
        if self.clarification_questions:
            raise ValueError("ready plan must not contain clarification questions")
        self._validate_ready_plan()
        return self

    def _validate_ready_plan(self) -> None:
        if self.intent == QueryIntent.COMPANY_LOOKUP:
            if self.metrics or not self.time.is_empty or self.period_type or self.statement_type:
                raise ValueError("company lookup must not contain financial metrics or periods")
            if self.comparison != ComparisonType.NONE:
                raise ValueError("company lookup does not support comparisons")
            return
        if self.entities.is_empty:
            raise ValueError("ready financial query requires a company or security")
        if not self.metrics:
            raise ValueError("ready financial query requires at least one metric")
        if self.time.is_empty:
            raise ValueError("ready financial query requires a time range")
        if self.intent == QueryIntent.MARKET_PRICE:
            if not self.entities.tickers:
                raise ValueError("market price query requires at least one ticker")
            if self.time.start_date is None:
                raise ValueError("market price query requires an exact date range")
            if self.period_type is not None or self.statement_type is not None:
                raise ValueError("market price query must not use financial report types")
        elif self.time.start_date is not None:
            raise ValueError("financial report query must use report_years")
        if self.intent != QueryIntent.FINANCIAL_STATEMENT and self.statement_type is not None:
            raise ValueError("statement_type is only valid for financial statements")
        if (
            self.comparison == ComparisonType.YEAR_OVER_YEAR
            and len(self.time.report_years) < 2
        ):
            raise ValueError("year-over-year comparison requires at least two report years")
