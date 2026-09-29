"""Application service for metric resolution, SQL guarding, and execution."""

from dataclasses import dataclass
from typing import Protocol

from finsight.domain.compiled_query import CompiledQuery
from finsight.domain.metric_catalog import ResolvedPlanMetrics
from finsight.domain.query_execution import GuardedQuery, QueryExecutionResult
from finsight.domain.query_plan import QueryIntent, StructuredQueryPlan
from finsight.security.structured_query_guard import guard_compiled_query
from finsight.services.metric_resolution import MetricResolver
from finsight.services.query_compiler import QueryCompiler
from finsight.services.query_schema_context import build_financial_query_schema


class QueryExecutor(Protocol):
    def execute(self, guarded: GuardedQuery) -> QueryExecutionResult: ...


@dataclass(frozen=True, slots=True)
class StructuredQueryOutcome:
    plan: StructuredQueryPlan
    resolved: ResolvedPlanMetrics | None
    compiled: CompiledQuery
    execution: QueryExecutionResult
    warnings: tuple[str, ...]


class StructuredQueryService:
    def __init__(
        self,
        executor: QueryExecutor,
        *,
        resolver: MetricResolver | None = None,
        compiler: QueryCompiler | None = None,
    ) -> None:
        self._executor = executor
        self._resolver = resolver or MetricResolver()
        self._compiler = compiler or QueryCompiler()
        self._schema = build_financial_query_schema()

    def execute(self, plan: StructuredQueryPlan) -> StructuredQueryOutcome:
        resolved = None
        if plan.intent != QueryIntent.COMPANY_LOOKUP:
            resolved = self._resolver.resolve_plan(plan)
        compiled = self._compiler.compile(plan, resolved)
        guarded = guard_compiled_query(compiled, self._schema)
        execution = self._executor.execute(guarded)
        warnings: list[str] = []
        if plan.intent in {
            QueryIntent.FINANCIAL_STATEMENT,
            QueryIntent.FINANCIAL_INDICATOR,
        }:
            warnings.append(
                "The current query does not apply a cross-source or revision-priority policy."
            )
        return StructuredQueryOutcome(
            plan=plan, resolved=resolved, compiled=compiled,
            execution=execution, warnings=tuple(warnings),
        )
