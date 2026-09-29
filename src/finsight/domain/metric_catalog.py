"""Reviewed financial metric vocabulary and resolved query metrics."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.financial_data import StatementType
from finsight.domain.query_plan import AggregationType


class MetricSource(StrEnum):
    FINANCIAL_STATEMENT = "financial_statement"
    FINANCIAL_INDICATOR = "financial_indicator"
    MARKET_PRICE = "market_price"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    source: MetricSource
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...] = Field(min_length=1)
    value_column: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    canonical_unit: str = Field(min_length=1, max_length=100)
    statement_type: StatementType | None = None
    allowed_aggregations: tuple[AggregationType, ...] = (AggregationType.NONE,)

    @model_validator(mode="after")
    def validate_definition(self) -> "MetricDefinition":
        if len(self.allowed_aggregations) != len(set(self.allowed_aggregations)):
            raise ValueError("allowed metric aggregations must be unique")
        if not self.allowed_aggregations:
            raise ValueError("metric needs at least one allowed aggregation")
        if (
            self.source == MetricSource.FINANCIAL_STATEMENT
            and self.statement_type is None
        ):
            raise ValueError("statement metric requires statement_type")
        if (
            self.source != MetricSource.FINANCIAL_STATEMENT
            and self.statement_type is not None
        ):
            raise ValueError("only statement metrics may define statement_type")
        return self


class MetricCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    metrics: tuple[MetricDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> "MetricCatalog":
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("metric IDs must be unique")
        source_codes = [(metric.source, metric.code) for metric in self.metrics]
        if len(source_codes) != len(set(source_codes)):
            raise ValueError("metric source/code pairs must be unique")
        return self


class ResolvedMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_term: str
    metric_id: str
    source: MetricSource
    code: str
    value_column: str
    canonical_unit: str
    statement_type: StatementType | None = None
    aggregation: AggregationType


class ResolvedPlanMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_version: str
    metrics: tuple[ResolvedMetric, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metrics(self) -> "ResolvedPlanMetrics":
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("resolved plan metrics must be unique")
        return self
