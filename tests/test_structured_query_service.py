from decimal import Decimal

from finsight.domain.query_execution import QueryExecutionResult
from finsight.domain.query_plan import (
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    TimeSelection,
)
from finsight.services.query_planning import build_query_plan
from finsight.services.structured_query import StructuredQueryService


class FakeExecutor:
    def __init__(self) -> None:
        self.guarded = None

    def execute(self, guarded):
        self.guarded = guarded
        columns = guarded.compiled.selected_columns
        row = {column: None for column in columns}
        row.update({"company_code": "CMB", "item_code": "revenue", "value": Decimal(100)})
        return QueryExecutionResult(
            query_sha256=guarded.compiled.query_sha256,
            sql_sha256="a" * 64, columns=columns, rows=(row,),
            row_count=1, execution_ms=2.5,
        )


def test_service_runs_resolution_compilation_guard_and_execution() -> None:
    plan = build_query_plan(
        "查询 CMB 2024 年营业收入", status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)), limit=10,
    )
    executor = FakeExecutor()
    outcome = StructuredQueryService(executor).execute(plan)
    assert outcome.resolved is not None
    assert outcome.resolved.metrics[0].code == "revenue"
    assert executor.guarded.verified_tables == ("financial_statements", "companies")
    assert outcome.execution.rows[0]["value"] == Decimal(100)
    assert "revision-priority" in outcome.warnings[0]
