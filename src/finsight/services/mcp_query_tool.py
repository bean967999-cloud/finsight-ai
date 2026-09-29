"""Authorized, audited adapter to the existing guarded financial-query service."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import ValidationError

from finsight.domain.mcp_tool_contracts import (
    QueryFinancialDataInput,
    QueryFinancialDataOutput,
    ToolCallContext,
    ToolErrorCode,
    ToolFailure,
    ToolName,
    tool_access_allowed,
)
from finsight.domain.query_plan import PlanStatus, StructuredQueryPlan
from finsight.services.mcp_tool_audit import ToolAudit
from finsight.services.metric_resolution import MetricResolutionError
from finsight.services.query_compiler import QueryCompilationError
from finsight.services.query_planning import build_query_plan
from finsight.services.read_only_query_executor import QueryExecutionError
from finsight.services.structured_query import StructuredQueryOutcome

_ROUTE = "/mcp/tools/query_financial_data"


class FinancialQueryService(Protocol):
    def execute(self, plan: StructuredQueryPlan) -> StructuredQueryOutcome: ...


def _safe_cell(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise ValueError("unsupported database value type")


class FinancialQueryTool:
    def __init__(self, audit: ToolAudit, service: FinancialQueryService) -> None:
        self._audit = audit
        self._service = service

    def execute(
        self, context: ToolCallContext, payload: QueryFinancialDataInput,
    ) -> QueryFinancialDataOutput | ToolFailure:
        try:
            self._audit.begin(
                context.request_id, action=ToolName.QUERY_FINANCIAL_DATA.value,
                method="MCP", route_pattern=_ROUTE, target_id=None,
            )
        except Exception:  # noqa: BLE001 - fail closed before any financial query
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")

        status_code = 500
        outcome: QueryFinancialDataOutput | ToolFailure
        try:
            if not tool_access_allowed(
                context, ToolName.QUERY_FINANCIAL_DATA, workspace_id=payload.workspace_id,
            ):
                status_code = 403
                outcome = ToolFailure(code=ToolErrorCode.ACCESS_DENIED, message="Access denied")
            else:
                plan = build_query_plan(
                    payload.query, status=PlanStatus.READY, intent=payload.intent,
                    entities=payload.entities, metrics=payload.metrics, time=payload.time,
                    period_type=payload.period_type, statement_type=payload.statement_type,
                    comparison=payload.comparison, order_by=payload.order_by,
                    limit=payload.limit,
                )
                result = self._service.execute(plan)
                rows = tuple(
                    {column: _safe_cell(row[column]) for column in result.execution.columns}
                    for row in result.execution.rows
                )
                outcome = QueryFinancialDataOutput(
                    columns=result.execution.columns, rows=rows,
                    row_count=result.execution.row_count,
                    sql_sha256=result.execution.sql_sha256,
                    warnings=result.warnings,
                )
                status_code = 200
        except (ValidationError, MetricResolutionError, QueryCompilationError, ValueError):
            status_code = 422
            outcome = ToolFailure(code=ToolErrorCode.INVALID_INPUT, message="Invalid query plan or result")
        except QueryExecutionError:
            status_code = 503
            outcome = ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Query source unavailable")
        except Exception:  # noqa: BLE001 - never return SQL, parameters or internal errors
            outcome = ToolFailure(code=ToolErrorCode.INTERNAL_ERROR, message="Financial query failed")

        try:
            self._audit.finish(
                context.request_id, status_code=status_code,
                actor_user_id=context.principal.user_id, workspace_id=payload.workspace_id,
            )
        except Exception:  # noqa: BLE001 - never release rows without completed audit
            return ToolFailure(code=ToolErrorCode.SOURCE_UNAVAILABLE, message="Audit unavailable")
        return outcome
