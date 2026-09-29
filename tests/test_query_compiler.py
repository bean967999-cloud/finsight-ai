from datetime import date

import pytest

from finsight.domain.financial_data import ReportingPeriodType, StatementType
from finsight.domain.query_plan import (
    AggregationType,
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    QueryOrder,
    TimeSelection,
)
from finsight.services.metric_resolution import MetricResolver
from finsight.services.query_compiler import QueryCompilationError, QueryCompiler
from finsight.services.query_planning import build_query_plan


def statement_plan(*, company_code: str = "CMB", order_field: str = "report_date"):
    return build_query_plan(
        "查询营业收入", status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=(company_code,)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2023, 2024)),
        period_type=ReportingPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
        order_by=(QueryOrder(field=order_field),), limit=20,
    )


def test_statement_sql_uses_fixed_identifiers_and_parameters() -> None:
    plan = statement_plan()
    compiled = QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))
    assert "FROM financial_statements AS fs" in compiled.sql
    assert "JOIN companies AS c ON c.id = fs.company_id" in compiled.sql
    assert "fs.item_code IN (:metric_code_0)" in compiled.sql
    assert "EXTRACT(YEAR FROM fs.report_date) IN (:report_year_0, :report_year_1)" in compiled.sql
    assert compiled.parameters == {
        "company_code_0": "CMB", "metric_code_0": "revenue",
        "statement_type_0": "income_statement", "report_year_0": 2023,
        "report_year_1": 2024, "period_type": "annual", "limit": 20,
    }
    assert compiled.source_tables == ("financial_statements", "companies")


def test_user_value_that_looks_like_injection_never_enters_sql() -> None:
    malicious = "CMB' OR 1=1 --"
    plan = statement_plan(company_code=malicious)
    compiled = QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))
    assert malicious not in compiled.sql
    assert compiled.parameters["company_code_0"] == malicious.upper()
    assert ";" not in compiled.sql


def test_market_aggregation_uses_allowlisted_function_and_date_parameters() -> None:
    plan = build_query_plan(
        "一月平均收盘价", status="ready", intent="market_price",
        entities=EntitySelection(tickers=("600036",), exchanges=("SSE",)),
        metrics=(MetricRequest(term="收盘价", aggregation=AggregationType.AVERAGE),),
        time=TimeSelection(start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)),
        order_by=(QueryOrder(field="close_price"),), limit=50,
    )
    compiled = QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))
    assert "AVG(mp.close_price) AS average_close_price" in compiled.sql
    assert "GROUP BY c.company_code" in compiled.sql
    assert "ORDER BY average_close_price ASC" in compiled.sql
    assert compiled.parameters["start_date"] == date(2025, 1, 1)
    assert "2025-01-01" not in compiled.sql


def test_unknown_order_field_and_mismatched_artifacts_are_rejected() -> None:
    invalid_order = statement_plan(order_field="data_source_id")
    with pytest.raises(QueryCompilationError, match="not allowed"):
        QueryCompiler().compile(invalid_order, MetricResolver().resolve_plan(invalid_order))

    first = statement_plan()
    second = build_query_plan(
        "另一个问题", status="ready", intent="financial_statement",
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)),
    )
    with pytest.raises(QueryCompilationError, match="different queries"):
        QueryCompiler().compile(first, MetricResolver().resolve_plan(second))


def test_company_lookup_compiles_without_metric_resolution() -> None:
    plan = build_query_plan(
        "列出公司", status="ready", intent="company_lookup",
        entities=EntitySelection(company_names=("演示公司",)), limit=10,
    )
    compiled = QueryCompiler().compile(plan)
    assert "FROM companies AS c" in compiled.sql
    assert compiled.parameters == {"company_name_0": "演示公司", "limit": 10}
