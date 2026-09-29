"""Authorized, audited adapter for the deterministic portfolio-risk tool."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from finsight.domain.mcp_tool_contracts import (
    CalculatePortfolioRiskInput,
    CalculatePortfolioRiskOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
    ToolName,
    tool_access_allowed,
)
from finsight.domain.schemas import RiskMetrics
from finsight.services.mcp_tool_audit import ToolAudit
from finsight.services.risk_engine import RiskEngine

_ROUTE = "/mcp/tools/calculate_portfolio_risk"


class RiskCalculator(Protocol):
    def analyze(
        self, prices: list[float], confidence: float = 0.95,
        trading_days: int = 252, risk_free_rate: float = 0.0,
    ) -> RiskMetrics: ...


class PortfolioRiskTool:
    def __init__(self, audit: ToolAudit, calculator: RiskCalculator | None = None) -> None:
        self._audit = audit
        self._calculator = calculator if calculator is not None else RiskEngine()

    def execute(
        self, context: ToolCallContext, payload: CalculatePortfolioRiskInput,
    ) -> CalculatePortfolioRiskOutput | ToolFailure:
        try:
            self._audit.begin(
                context.request_id, action=ToolName.CALCULATE_PORTFOLIO_RISK.value,
                method="MCP", route_pattern=_ROUTE, target_id=None,
            )
        except Exception:  # noqa: BLE001 - audit failure must prevent tool execution
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")

        status_code = 500
        outcome: CalculatePortfolioRiskOutput | ToolFailure
        try:
            if not tool_access_allowed(
                context, ToolName.CALCULATE_PORTFOLIO_RISK,
                workspace_id=payload.workspace_id,
            ):
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            else:
                metrics = self._calculator.analyze(
                    list(payload.prices), confidence=payload.confidence,
                    trading_days=payload.trading_days, risk_free_rate=payload.risk_free_rate,
                )
                outcome = CalculatePortfolioRiskOutput(metrics=metrics)
                status_code = 200
        except (ValueError, ValidationError):
            status_code = 422
            outcome = ToolFailure(code=ToolErrorCode.INVALID_INPUT, message="Invalid risk input")
        except Exception:  # noqa: BLE001 - do not reveal calculator internals or caller prices
            outcome = ToolFailure(code=ToolErrorCode.INTERNAL_ERROR, message="Risk calculation failed")

        try:
            self._audit.finish(
                context.request_id, status_code=status_code,
                actor_user_id=context.principal.user_id, workspace_id=payload.workspace_id,
            )
        except Exception:  # noqa: BLE001 - fail closed even if calculation succeeded
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")
        return outcome
