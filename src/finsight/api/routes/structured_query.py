"""Versioned structured financial query endpoint."""

from datetime import date
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finsight.domain.compiled_query import SQLParameter
from finsight.domain.financial_data import ReportingPeriodType, StatementType
from finsight.domain.metric_catalog import ResolvedMetric
from finsight.domain.query_plan import (
    ComparisonType,
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    QueryOrder,
    StructuredQueryPlan,
    TimeSelection,
)
from finsight.services.metric_resolution import MetricResolutionError
from finsight.services.query_compiler import QueryCompilationError
from finsight.services.query_planning import build_query_plan
from finsight.services.read_only_query_executor import QueryExecutionError
from finsight.services.structured_query import StructuredQueryOutcome

router = APIRouter(prefix="/api/v1/query", tags=["structured-query"])


class StructuredQueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=2000)
    intent: QueryIntent
    entities: EntitySelection = EntitySelection()
    metrics: tuple[MetricRequest, ...] = ()
    time: TimeSelection = TimeSelection()
    period_type: ReportingPeriodType | None = None
    statement_type: StatementType | None = None
    comparison: ComparisonType = ComparisonType.NONE
    order_by: tuple[QueryOrder, ...] = ()
    limit: int = Field(default=100, ge=1, le=500)


class QueryDataPeriod(BaseModel):
    report_years: tuple[int, ...] = ()
    start_date: date | None = None
    end_date: date | None = None


class StructuredQueryResponse(BaseModel):
    plan: StructuredQueryPlan
    resolved_metrics: tuple[ResolvedMetric, ...]
    catalog_version: str | None
    sql_template: str
    parameters: dict[str, SQLParameter]
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    execution_ms: float
    sql_sha256: str
    data_period: QueryDataPeriod
    warnings: tuple[str, ...]


class StructuredQueryUseCase(Protocol):
    def execute(self, plan: StructuredQueryPlan) -> StructuredQueryOutcome: ...


def get_structured_query(request: Request) -> StructuredQueryUseCase:
    service = getattr(request.app.state, "structured_query", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="structured query is not configured on this process",
        )
    return service


@router.post("/structured", response_model=StructuredQueryResponse)
def execute_structured_query(
    payload: StructuredQueryRequest,
    service: Annotated[StructuredQueryUseCase, Depends(get_structured_query)],
) -> StructuredQueryResponse:
    try:
        plan = build_query_plan(
            payload.query,
            status=PlanStatus.READY,
            intent=payload.intent,
            entities=payload.entities,
            metrics=payload.metrics,
            time=payload.time,
            period_type=payload.period_type,
            statement_type=payload.statement_type,
            comparison=payload.comparison,
            order_by=payload.order_by,
            limit=payload.limit,
        )
        outcome = service.execute(plan)
    except (ValidationError, MetricResolutionError, QueryCompilationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except QueryExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="structured query execution failed",
        ) from exc
    resolved_metrics = () if outcome.resolved is None else outcome.resolved.metrics
    catalog_version = None if outcome.resolved is None else outcome.resolved.catalog_version
    return StructuredQueryResponse(
        plan=outcome.plan,
        resolved_metrics=resolved_metrics,
        catalog_version=catalog_version,
        sql_template=outcome.compiled.sql,
        parameters=outcome.compiled.parameters,
        columns=outcome.execution.columns,
        rows=outcome.execution.rows,
        row_count=outcome.execution.row_count,
        execution_ms=outcome.execution.execution_ms,
        sql_sha256=outcome.execution.sql_sha256,
        data_period=QueryDataPeriod(
            report_years=outcome.plan.time.report_years,
            start_date=outcome.plan.time.start_date,
            end_date=outcome.plan.time.end_date,
        ),
        warnings=outcome.warnings,
    )
