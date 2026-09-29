"""Day17 Step3: tool reuses the guarded query service without exposing SQL text."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.mcp_tool_contracts import (
    QueryFinancialDataInput,
    QueryFinancialDataOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
)
from finsight.domain.query_execution import QueryExecutionResult
from finsight.domain.query_plan import EntitySelection, MetricRequest, TimeSelection
from finsight.services.mcp_query_tool import FinancialQueryTool
from finsight.services.read_only_query_executor import QueryExecutionError
from finsight.services.structured_query import StructuredQueryService

WORKSPACE = UUID(int=22)


class MemoryAudit:
    def __init__(self, *, fail_begin=False, fail_finish=False) -> None:
        self.events = []
        self.fail_begin = fail_begin
        self.fail_finish = fail_finish

    def begin(self, request_id, *, action, method, route_pattern, target_id) -> None:
        if self.fail_begin:
            raise RuntimeError("private audit detail")
        self.events.append(("begin", action, method, route_pattern))

    def finish(self, request_id, *, status_code, actor_user_id=None, workspace_id=None, knowledge_base_id=None) -> None:
        if self.fail_finish:
            raise RuntimeError("private audit detail")
        self.events.append(("finish", status_code, workspace_id))


class FakeExecutor:
    def __init__(self, *, fail=False) -> None:
        self.calls = 0
        self.guarded = None
        self.fail = fail

    def execute(self, guarded):
        self.calls += 1
        self.guarded = guarded
        if self.fail:
            raise QueryExecutionError("private SQL or database detail")
        columns = guarded.compiled.selected_columns
        row = {column: None for column in columns}
        row.update({
            "company_code": "CMB", "report_date": date(2024, 12, 31),
            "value": Decimal("456.780000"),
        })
        return QueryExecutionResult(
            query_sha256=guarded.compiled.query_sha256,
            sql_sha256="a" * 64, columns=columns, rows=(row,),
            row_count=1, execution_ms=1.0,
        )


def context(role: Role, workspace: UUID = WORKSPACE) -> ToolCallContext:
    return ToolCallContext(
        principal=Principal(user_id=UUID(int=21), memberships=(WorkspaceMembership(
            workspace_id=workspace, role=role,
        ),)),
        request_id=UUID(int=23),
    )


def payload() -> QueryFinancialDataInput:
    return QueryFinancialDataInput(
        workspace_id=WORKSPACE, query="查询 CMB 2024 年营业收入",
        intent="financial_statement",
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)),
        period_type="annual", statement_type="income_statement", limit=10,
    )


def test_tool_reuses_resolution_compilation_guard_and_serializes_exact_decimal() -> None:
    audit = MemoryAudit()
    executor = FakeExecutor()
    result = FinancialQueryTool(audit, StructuredQueryService(executor)).execute(
        context(Role.RESEARCHER), payload()
    )
    assert isinstance(result, QueryFinancialDataOutput)
    assert result.rows[0]["value"] == "456.780000"
    assert result.rows[0]["report_date"] == "2024-12-31"
    assert result.sql_sha256 == "a" * 64
    assert "revision-priority" in result.warnings[0]
    assert executor.calls == 1
    assert executor.guarded.verified_tables == ("financial_statements", "companies")
    assert executor.guarded.compiled.max_rows == 10
    assert audit.events[0] == (
        "begin", "query_financial_data", "MCP", "/mcp/tools/query_financial_data"
    )
    assert audit.events[1][1] == 200
    assert "SELECT" not in result.model_dump_json()


def test_denied_scope_and_audit_failure_never_execute_query() -> None:
    for principal in (context(Role.VIEWER), context(Role.RESEARCHER, UUID(int=99))):
        executor = FakeExecutor()
        audit = MemoryAudit()
        result = FinancialQueryTool(audit, StructuredQueryService(executor)).execute(principal, payload())
        assert isinstance(result, ToolFailure)
        assert result.code == ToolErrorCode.ACCESS_DENIED
        assert executor.calls == 0
        assert audit.events[1][1] == 403

    executor = FakeExecutor()
    result = FinancialQueryTool(MemoryAudit(fail_begin=True), StructuredQueryService(executor)).execute(
        context(Role.RESEARCHER), payload()
    )
    assert isinstance(result, ToolFailure)
    assert result.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert executor.calls == 0


def test_query_failure_is_sanitized_and_audit_finish_failure_hides_rows() -> None:
    result = FinancialQueryTool(
        MemoryAudit(), StructuredQueryService(FakeExecutor(fail=True))
    ).execute(context(Role.RESEARCHER), payload())
    assert isinstance(result, ToolFailure)
    assert result.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert "private" not in result.model_dump_json()

    result = FinancialQueryTool(
        MemoryAudit(fail_finish=True), StructuredQueryService(FakeExecutor())
    ).execute(context(Role.RESEARCHER), payload())
    assert isinstance(result, ToolFailure)
    assert result.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert "456" not in result.model_dump_json()


def test_contract_rejects_raw_sql_and_unbounded_rows() -> None:
    with pytest.raises(ValidationError):
        QueryFinancialDataInput.model_validate({**payload().model_dump(), "sql": "DROP TABLE x"})
    with pytest.raises(ValidationError):
        QueryFinancialDataInput.model_validate({**payload().model_dump(), "limit": 101})
