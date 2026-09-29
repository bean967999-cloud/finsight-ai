from datetime import date

import pytest
from pydantic import ValidationError

from finsight.domain.financial_data import ReportingPeriodType, StatementType
from finsight.domain.query_plan import (
    ComparisonType,
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    QueryOrder,
    SortDirection,
    TimeSelection,
)
from finsight.services.query_planning import build_query_plan, query_digest


def test_ready_financial_statement_plan_is_explicit_and_traceable() -> None:
    plan = build_query_plan(
        "比较 CMB 2023 和 2024 年的营业收入",
        status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("cmb",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2023, 2024)),
        period_type=ReportingPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
        comparison=ComparisonType.YEAR_OVER_YEAR,
        order_by=(QueryOrder(field="report_date", direction=SortDirection.ASCENDING),),
        limit=20,
    )
    assert plan.entities.company_codes == ("CMB",)
    assert plan.query_sha256 == query_digest("比较 CMB 2023 和 2024 年的营业收入")
    assert not hasattr(plan, "query")


def test_market_price_plan_requires_ticker_and_exact_date_range() -> None:
    plan = build_query_plan(
        "查询 600036 在一月份的收盘价",
        status="ready", intent="market_price",
        entities=EntitySelection(tickers=("600036",), exchanges=("sse",)),
        metrics=(MetricRequest(term="收盘价"),),
        time=TimeSelection(start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)),
    )
    assert plan.entities.exchanges == ("SSE",)
    with pytest.raises(ValidationError, match="exact date range"):
        build_query_plan(
            "查询收盘价", status="ready", intent="market_price",
            entities=EntitySelection(tickers=("600036",)),
            metrics=(MetricRequest(term="收盘价"),),
            time=TimeSelection(report_years=(2025,)),
        )


def test_missing_information_becomes_clarification_instead_of_guessing() -> None:
    plan = build_query_plan(
        "查询营业收入",
        status=PlanStatus.NEEDS_CLARIFICATION,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        metrics=(MetricRequest(term="营业收入"),),
        clarification_questions=("请指定公司和报告年份。",),
    )
    assert plan.status == PlanStatus.NEEDS_CLARIFICATION
    with pytest.raises(ValidationError, match="requires at least one question"):
        build_query_plan(
            "查询营业收入", status="needs_clarification",
            intent="financial_statement",
        )


def test_ready_plan_rejects_missing_scope_and_invalid_combinations() -> None:
    with pytest.raises(ValidationError, match="requires a company or security"):
        build_query_plan(
            "2024 年营业收入", status="ready", intent="financial_statement",
            metrics=(MetricRequest(term="营业收入"),),
            time=TimeSelection(report_years=(2024,)),
        )
    with pytest.raises(ValidationError, match="at least two report years"):
        build_query_plan(
            "同比营业收入", status="ready", intent="financial_statement",
            entities=EntitySelection(company_codes=("CMB",)),
            metrics=(MetricRequest(term="营业收入"),),
            time=TimeSelection(report_years=(2024,)),
            comparison="year_over_year",
        )
    with pytest.raises(ValidationError, match="only valid for financial statements"):
        build_query_plan(
            "2024 年净资产收益率", status="ready", intent="financial_indicator",
            entities=EntitySelection(company_codes=("CMB",)),
            metrics=(MetricRequest(term="净资产收益率"),),
            time=TimeSelection(report_years=(2024,)),
            statement_type=StatementType.INCOME_STATEMENT,
        )


def test_duplicate_metrics_years_and_sort_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="metric requests must be unique"):
        build_query_plan(
            "重复指标", status="ready", intent="financial_indicator",
            entities=EntitySelection(company_codes=("CMB",)),
            metrics=(MetricRequest(term="ROE"), MetricRequest(term="roe")),
            time=TimeSelection(report_years=(2024,)),
        )
    with pytest.raises(ValidationError, match="report_years must be unique"):
        TimeSelection(report_years=(2024, 2024))
    with pytest.raises(ValidationError, match="order_by fields must be unique"):
        build_query_plan(
            "重复排序", status="ready", intent="financial_indicator",
            entities=EntitySelection(company_codes=("CMB",)),
            metrics=(MetricRequest(term="ROE"),), time=TimeSelection(report_years=(2024,)),
            order_by=(QueryOrder(field="value"), QueryOrder(field="value")),
        )
