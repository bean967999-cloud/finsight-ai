"""Day17 Step2: risk tool reuses the calculator and fails closed on audit/authorization."""

from uuid import UUID

import pytest

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.domain.mcp_tool_contracts import (
    CalculatePortfolioRiskInput,
    CalculatePortfolioRiskOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
)
from finsight.services.mcp_risk_tool import PortfolioRiskTool

WORKSPACE = UUID(int=12)


class MemoryAudit:
    def __init__(self, *, fail_begin: bool = False, fail_finish: bool = False) -> None:
        self.events: list[tuple[str, object]] = []
        self.fail_begin = fail_begin
        self.fail_finish = fail_finish

    def begin(self, request_id, *, action, method, route_pattern, target_id) -> None:
        if self.fail_begin:
            raise RuntimeError("private audit detail")
        self.events.append(("begin", (request_id, action, method, route_pattern, target_id)))

    def finish(self, request_id, *, status_code, actor_user_id=None, workspace_id=None, knowledge_base_id=None) -> None:
        if self.fail_finish:
            raise RuntimeError("private audit detail")
        self.events.append(("finish", (request_id, status_code, actor_user_id, workspace_id)))


class CountingCalculator:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, prices, confidence=0.95, trading_days=252, risk_free_rate=0.0):
        self.calls += 1
        raise RuntimeError("private prices or implementation detail")


def context(role: Role, *, workspace: UUID = WORKSPACE) -> ToolCallContext:
    return ToolCallContext(
        principal=Principal(user_id=UUID(int=11), memberships=(WorkspaceMembership(
            workspace_id=workspace, role=role,
        ),)),
        request_id=UUID(int=13),
    )


def payload() -> CalculatePortfolioRiskInput:
    return CalculatePortfolioRiskInput(workspace_id=WORKSPACE, prices=(100, 90, 99))


def test_authorized_tool_reuses_deterministic_engine_and_audits() -> None:
    audit = MemoryAudit()
    result = PortfolioRiskTool(audit).execute(context(Role.RESEARCHER), payload())
    assert isinstance(result, CalculatePortfolioRiskOutput)
    assert result.metrics.cumulative_return == pytest.approx(-0.01)
    assert result.metrics.max_drawdown == pytest.approx(-0.1)
    assert result.metrics.historical_var >= 0
    assert result.metrics.historical_cvar >= result.metrics.historical_var
    assert result.source == "caller_supplied_prices"
    assert len(result.limitations) == 1
    assert audit.events[0][1][1:4] == (
        "calculate_portfolio_risk", "MCP", "/mcp/tools/calculate_portfolio_risk"
    )
    assert audit.events[1][1][1] == 200
    assert "100" not in str(audit.events)


def test_denied_roles_and_workspace_do_not_execute_calculator() -> None:
    for principal in (context(Role.VIEWER), context(Role.RESEARCHER, workspace=UUID(int=99))):
        audit = MemoryAudit()
        calculator = CountingCalculator()
        result = PortfolioRiskTool(audit, calculator).execute(principal, payload())
        assert isinstance(result, ToolFailure)
        assert result.code == ToolErrorCode.ACCESS_DENIED
        assert calculator.calls == 0
        assert audit.events[1][1][1] == 403


def test_audit_failure_fails_closed_and_calculator_error_is_sanitized() -> None:
    calculator = CountingCalculator()
    unavailable = PortfolioRiskTool(MemoryAudit(fail_begin=True), calculator).execute(
        context(Role.RESEARCHER), payload()
    )
    assert isinstance(unavailable, ToolFailure)
    assert unavailable.code == ToolErrorCode.SOURCE_UNAVAILABLE
    assert calculator.calls == 0

    broken = PortfolioRiskTool(MemoryAudit(), calculator).execute(context(Role.RESEARCHER), payload())
    assert isinstance(broken, ToolFailure)
    assert broken.code == ToolErrorCode.INTERNAL_ERROR
    assert "private" not in broken.model_dump_json()

    after_calculation = PortfolioRiskTool(MemoryAudit(fail_finish=True)).execute(
        context(Role.RESEARCHER), payload()
    )
    assert isinstance(after_calculation, ToolFailure)
    assert after_calculation.code == ToolErrorCode.SOURCE_UNAVAILABLE
