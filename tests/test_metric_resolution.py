import pytest

from finsight.domain.financial_data import ReportingPeriodType, StatementType
from finsight.domain.query_plan import (
    AggregationType,
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    TimeSelection,
)
from finsight.services.metric_resolution import (
    AmbiguousMetricError,
    MetricIntentMismatchError,
    MetricResolutionError,
    MetricResolver,
    UnknownMetricError,
    normalize_metric_term,
)
from finsight.services.query_planning import build_query_plan


def test_statement_alias_resolves_to_reviewed_code_type_and_unit() -> None:
    resolved = MetricResolver().resolve(
        MetricRequest(term="营 收"), QueryIntent.FINANCIAL_STATEMENT,
    )
    assert resolved.metric_id == "statement.revenue"
    assert resolved.code == "revenue"
    assert resolved.statement_type == StatementType.INCOME_STATEMENT
    assert resolved.canonical_unit == "row.currency + row.unit"
    assert normalize_metric_term("TOTAL_Revenue") == "totalrevenue"


def test_indicator_and_market_aliases_resolve_without_fuzzy_guessing() -> None:
    resolver = MetricResolver()
    roe = resolver.resolve(MetricRequest(term="RoE"), QueryIntent.FINANCIAL_INDICATOR)
    close = resolver.resolve(MetricRequest(term="收盘价"), QueryIntent.MARKET_PRICE)
    assert (roe.code, roe.canonical_unit) == ("roe", "%")
    assert (close.code, close.value_column) == ("close_price", "close_price")


def test_unknown_ambiguous_and_wrong_intent_are_explicit_errors() -> None:
    resolver = MetricResolver()
    with pytest.raises(UnknownMetricError, match="unknown metric"):
        resolver.resolve(MetricRequest(term="神秘指标"), QueryIntent.FINANCIAL_INDICATOR)
    with pytest.raises(AmbiguousMetricError, match="statement.revenue.*total_revenue"):
        resolver.resolve(MetricRequest(term="收入"), QueryIntent.FINANCIAL_STATEMENT)
    with pytest.raises(MetricIntentMismatchError, match="financial_indicator"):
        resolver.resolve(MetricRequest(term="ROE"), QueryIntent.FINANCIAL_STATEMENT)


def test_unsafe_aggregation_is_rejected_by_metric_definition() -> None:
    resolver = MetricResolver()
    with pytest.raises(MetricResolutionError, match="not allowed"):
        resolver.resolve(
            MetricRequest(term="ROE", aggregation=AggregationType.AVERAGE),
            QueryIntent.FINANCIAL_INDICATOR,
        )
    volume = resolver.resolve(
        MetricRequest(term="成交量", aggregation=AggregationType.SUM),
        QueryIntent.MARKET_PRICE,
    )
    assert volume.aggregation == AggregationType.SUM


def test_ready_plan_resolves_with_catalog_version_and_type_consistency() -> None:
    plan = build_query_plan(
        "查询 CMB 2024 年营业收入", status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)),
        period_type=ReportingPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
    )
    resolved = MetricResolver().resolve_plan(plan)
    assert resolved.query_sha256 == plan.query_sha256
    assert resolved.catalog_version == "v1"
    assert resolved.metrics[0].code == "revenue"

    mismatch = plan.model_copy(update={"statement_type": StatementType.BALANCE_SHEET})
    with pytest.raises(MetricIntentMismatchError, match="does not match"):
        MetricResolver().resolve_plan(mismatch)
