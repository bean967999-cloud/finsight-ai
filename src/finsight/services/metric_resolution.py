"""Exact, allowlisted metric resolution with explicit ambiguity handling."""

import unicodedata

from finsight.domain.financial_data import StatementType
from finsight.domain.metric_catalog import (
    MetricCatalog,
    MetricDefinition,
    MetricSource,
    ResolvedMetric,
    ResolvedPlanMetrics,
)
from finsight.domain.query_plan import (
    AggregationType,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    StructuredQueryPlan,
)


class MetricResolutionError(ValueError):
    pass


class UnknownMetricError(MetricResolutionError):
    pass


class AmbiguousMetricError(MetricResolutionError):
    pass


class MetricIntentMismatchError(MetricResolutionError):
    pass


_INTENT_SOURCE = {
    QueryIntent.FINANCIAL_STATEMENT: MetricSource.FINANCIAL_STATEMENT,
    QueryIntent.FINANCIAL_INDICATOR: MetricSource.FINANCIAL_INDICATOR,
    QueryIntent.MARKET_PRICE: MetricSource.MARKET_PRICE,
}


def normalize_metric_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character not in " _-\t\r\n")


def build_metric_catalog() -> MetricCatalog:
    no_aggregation = (AggregationType.NONE,)
    price_aggregations = (
        AggregationType.NONE, AggregationType.AVERAGE,
        AggregationType.MINIMUM, AggregationType.MAXIMUM,
    )
    flow_aggregations = (*price_aggregations, AggregationType.SUM)
    return MetricCatalog(version="v1", metrics=(
        MetricDefinition(
            metric_id="statement.revenue", source=MetricSource.FINANCIAL_STATEMENT,
            code="revenue",
            display_name="营业收入", aliases=("营业收入", "营收", "revenue", "收入"),
            value_column="value", canonical_unit="row.currency + row.unit",
            statement_type=StatementType.INCOME_STATEMENT,
            allowed_aggregations=no_aggregation,
        ),
        MetricDefinition(
            metric_id="statement.total_revenue", source=MetricSource.FINANCIAL_STATEMENT,
            code="total_revenue", display_name="营业总收入",
            aliases=("营业总收入", "总营收", "total revenue", "total_revenue", "收入"),
            value_column="value", canonical_unit="row.currency + row.unit",
            statement_type=StatementType.INCOME_STATEMENT,
            allowed_aggregations=no_aggregation,
        ),
        MetricDefinition(
            metric_id="statement.net_profit_attributable",
            source=MetricSource.FINANCIAL_STATEMENT,
            code="n_income_attr_p", display_name="归属于母公司股东的净利润",
            aliases=("归母净利润", "归属于母公司股东的净利润", "n_income_attr_p"),
            value_column="value", canonical_unit="row.currency + row.unit",
            statement_type=StatementType.INCOME_STATEMENT,
            allowed_aggregations=no_aggregation,
        ),
        MetricDefinition(
            metric_id="indicator.roe", source=MetricSource.FINANCIAL_INDICATOR, code="roe",
            display_name="净资产收益率", aliases=("净资产收益率", "ROE", "roe"),
            value_column="value", canonical_unit="%",
            allowed_aggregations=no_aggregation,
        ),
        MetricDefinition(
            metric_id="indicator.debt_to_assets", source=MetricSource.FINANCIAL_INDICATOR,
            code="debt_to_assets", display_name="资产负债率",
            aliases=("资产负债率", "debt to assets", "debt_to_assets"),
            value_column="value", canonical_unit="%",
            allowed_aggregations=no_aggregation,
        ),
        *(
            MetricDefinition(
                metric_id=f"market.{code}", source=MetricSource.MARKET_PRICE, code=code,
                display_name=display, aliases=aliases, value_column=code,
                canonical_unit=unit, allowed_aggregations=aggregations,
            )
            for code, display, aliases, unit, aggregations in (
                ("open_price", "开盘价", ("开盘价", "open", "open_price"), "security.currency/股", price_aggregations),
                ("high_price", "最高价", ("最高价", "high", "high_price"), "security.currency/股", price_aggregations),
                ("low_price", "最低价", ("最低价", "low", "low_price"), "security.currency/股", price_aggregations),
                ("close_price", "收盘价", ("收盘价", "close", "close_price"), "security.currency/股", price_aggregations),
                ("volume", "成交量", ("成交量", "volume"), "股", flow_aggregations),
                ("amount", "成交额", ("成交额", "成交金额", "amount"), "security.currency", flow_aggregations),
            )
        ),
    ))


class MetricResolver:
    def __init__(self, catalog: MetricCatalog | None = None) -> None:
        self.catalog = catalog or build_metric_catalog()

    def resolve(self, request: MetricRequest, intent: QueryIntent) -> ResolvedMetric:
        if intent == QueryIntent.COMPANY_LOOKUP:
            raise MetricIntentMismatchError("company lookup does not accept financial metrics")
        normalized = normalize_metric_term(request.term)
        matches = [
            metric for metric in self.catalog.metrics
            if normalized in self._terms(metric)
        ]
        if not matches:
            raise UnknownMetricError(f"unknown metric term: {request.term}")
        expected_source = _INTENT_SOURCE[intent]
        compatible = [metric for metric in matches if metric.source == expected_source]
        if not compatible:
            sources = ", ".join(sorted({metric.source.value for metric in matches}))
            raise MetricIntentMismatchError(
                f"metric '{request.term}' belongs to {sources}, not {intent.value}"
            )
        if len(compatible) > 1:
            choices = ", ".join(metric.metric_id for metric in compatible)
            raise AmbiguousMetricError(
                f"metric term '{request.term}' is ambiguous; choose one of: {choices}"
            )
        definition = compatible[0]
        if request.aggregation not in definition.allowed_aggregations:
            allowed = ", ".join(item.value for item in definition.allowed_aggregations)
            raise MetricResolutionError(
                f"aggregation '{request.aggregation.value}' is not allowed for "
                f"{definition.metric_id}; allowed: {allowed}"
            )
        return ResolvedMetric(
            requested_term=request.term, metric_id=definition.metric_id,
            source=definition.source, code=definition.code,
            value_column=definition.value_column,
            canonical_unit=definition.canonical_unit,
            statement_type=definition.statement_type,
            aggregation=request.aggregation,
        )

    def resolve_plan(self, plan: StructuredQueryPlan) -> ResolvedPlanMetrics:
        if plan.status != PlanStatus.READY:
            raise MetricResolutionError("only ready plans can resolve metrics")
        if not plan.metrics:
            raise MetricResolutionError("plan has no metrics to resolve")
        resolved = tuple(self.resolve(metric, plan.intent) for metric in plan.metrics)
        metric_ids = [metric.metric_id for metric in resolved]
        if len(metric_ids) != len(set(metric_ids)):
            raise MetricResolutionError("plan terms resolve to duplicate canonical metrics")
        statement_types = {
            metric.statement_type for metric in resolved if metric.statement_type is not None
        }
        if plan.statement_type is not None and statement_types != {plan.statement_type}:
            raise MetricIntentMismatchError(
                "resolved statement metric does not match plan statement_type"
            )
        return ResolvedPlanMetrics(
            query_sha256=plan.query_sha256,
            catalog_version=self.catalog.version,
            metrics=resolved,
        )

    @staticmethod
    def _terms(metric: MetricDefinition) -> set[str]:
        return {
            normalize_metric_term(value)
            for value in (metric.code, metric.display_name, *metric.aliases)
        }
