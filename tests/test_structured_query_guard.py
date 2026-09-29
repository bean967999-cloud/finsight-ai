import pytest

from finsight.domain.query_plan import (
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    TimeSelection,
)
from finsight.security.sql_guard import SQLGuardError
from finsight.security.structured_query_guard import guard_compiled_query
from finsight.services.metric_resolution import MetricResolver
from finsight.services.query_compiler import QueryCompiler
from finsight.services.query_planning import build_query_plan
from finsight.services.query_schema_context import build_financial_query_schema


def compiled_statement():
    plan = build_query_plan(
        "查询营业收入", status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)), limit=20,
    )
    return QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))


def test_compiled_query_passes_table_column_function_and_limit_checks() -> None:
    guarded = guard_compiled_query(compiled_statement(), build_financial_query_schema())
    assert guarded.verified_tables == ("financial_statements", "companies")
    assert "financial_statements.value" in guarded.verified_columns
    assert guarded.compiled.parameters["limit"] == 20


@pytest.mark.parametrize(
    "replacement, message",
    [
        ("FROM import_jobs AS fs", "not in the query allowlist"),
        ("fs.secret_value", "not in the query allowlist"),
        ("SELECT *", "SELECT \\* is not allowed"),
    ],
)
def test_tampered_table_column_and_star_are_rejected(replacement: str, message: str) -> None:
    compiled = compiled_statement()
    if replacement.startswith("FROM"):
        sql = compiled.sql.replace("FROM financial_statements AS fs", replacement)
    elif replacement == "SELECT *":
        sql = replacement + compiled.sql[compiled.sql.index("\nFROM"):]
    else:
        sql = compiled.sql.replace("fs.value", replacement)
    with pytest.raises(SQLGuardError, match=message):
        guard_compiled_query(
            compiled.model_copy(update={"sql": sql}), build_financial_query_schema(),
        )


def test_comments_subqueries_functions_and_limit_tampering_are_rejected() -> None:
    compiled = compiled_statement()
    with pytest.raises(SQLGuardError, match="comments"):
        guard_compiled_query(
            compiled.model_copy(update={"sql": compiled.sql + " -- bypass"}),
            build_financial_query_schema(),
        )
    sql = compiled.sql.replace("fs.value", "pg_sleep(1) AS value")
    with pytest.raises(SQLGuardError, match="function"):
        guard_compiled_query(compiled.model_copy(update={"sql": sql}), build_financial_query_schema())
    with pytest.raises(SQLGuardError, match="LIMIT"):
        guard_compiled_query(
            compiled.model_copy(update={"parameters": {**compiled.parameters, "limit": 500}}),
            build_financial_query_schema(),
        )
