"""Compile reviewed query plans into parameterized PostgreSQL SELECT templates."""

from collections.abc import Iterable

from finsight.domain.compiled_query import CompiledQuery, SQLParameter
from finsight.domain.metric_catalog import MetricSource, ResolvedPlanMetrics
from finsight.domain.query_plan import (
    AggregationType,
    PlanStatus,
    QueryIntent,
    SortDirection,
    StructuredQueryPlan,
)


class QueryCompilationError(ValueError):
    pass


_AGGREGATE_SQL = {
    AggregationType.AVERAGE: "AVG",
    AggregationType.MINIMUM: "MIN",
    AggregationType.MAXIMUM: "MAX",
    AggregationType.SUM: "SUM",
}


class QueryCompiler:
    def compile(
        self,
        plan: StructuredQueryPlan,
        resolved: ResolvedPlanMetrics | None = None,
    ) -> CompiledQuery:
        if plan.status != PlanStatus.READY:
            raise QueryCompilationError("only ready plans can be compiled")
        if plan.intent == QueryIntent.COMPANY_LOOKUP:
            if resolved is not None:
                raise QueryCompilationError("company lookup must not have resolved metrics")
            return self._compile_company(plan)
        if resolved is None:
            raise QueryCompilationError("financial query requires resolved metrics")
        if resolved.query_sha256 != plan.query_sha256:
            raise QueryCompilationError("plan and resolved metrics refer to different queries")
        expected_source = {
            QueryIntent.FINANCIAL_STATEMENT: MetricSource.FINANCIAL_STATEMENT,
            QueryIntent.FINANCIAL_INDICATOR: MetricSource.FINANCIAL_INDICATOR,
            QueryIntent.MARKET_PRICE: MetricSource.MARKET_PRICE,
        }[plan.intent]
        if any(metric.source != expected_source for metric in resolved.metrics):
            raise QueryCompilationError("resolved metric source does not match plan intent")
        if plan.intent == QueryIntent.FINANCIAL_STATEMENT:
            return self._compile_statements(plan, resolved)
        if plan.intent == QueryIntent.FINANCIAL_INDICATOR:
            return self._compile_indicators(plan, resolved)
        return self._compile_market(plan, resolved)

    def _compile_company(self, plan: StructuredQueryPlan) -> CompiledQuery:
        parameters: dict[str, SQLParameter] = {}
        select_columns = (
            "company_code", "legal_name", "short_name", "industry", "country",
            "established_date", "status",
        )
        sql = [
            "SELECT c.company_code, c.legal_name, c.short_name, c.industry, c.country,",
            "       c.established_date, c.status",
            "FROM companies AS c",
        ]
        joins, filters, tables = self._entity_clauses(plan, parameters, company_only=True)
        sql.extend(joins)
        self._append_where(sql, filters)
        self._append_order(
            sql, plan,
            {
                "company_code": "c.company_code", "legal_name": "c.legal_name",
                "industry": "c.industry", "established_date": "c.established_date",
            },
            default="c.company_code ASC",
        )
        parameters["limit"] = plan.limit
        sql.append("LIMIT :limit")
        return self._result(
            plan, sql, parameters, select_columns, ("companies", *tables),
        )

    def _compile_statements(
        self, plan: StructuredQueryPlan, resolved: ResolvedPlanMetrics,
    ) -> CompiledQuery:
        parameters: dict[str, SQLParameter] = {}
        select_columns = (
            "company_code", "legal_name", "report_date", "period_type",
            "statement_type", "item_code", "item_name", "value", "currency",
            "unit", "consolidation_scope",
        )
        sql = [
            "SELECT c.company_code, c.legal_name, fs.report_date, fs.period_type,",
            "       fs.statement_type, fs.item_code, fs.item_name, fs.value,",
            "       fs.currency, fs.unit, fs.consolidation_scope",
            "FROM financial_statements AS fs",
            "JOIN companies AS c ON c.id = fs.company_id",
        ]
        joins, filters, tables = self._entity_clauses(plan, parameters)
        sql.extend(joins)
        filters.append(self._in_clause(
            "fs.item_code", "metric_code", [item.code for item in resolved.metrics], parameters,
        ))
        statement_types = sorted({item.statement_type.value for item in resolved.metrics if item.statement_type})
        filters.append(self._in_clause(
            "fs.statement_type", "statement_type", statement_types, parameters,
        ))
        self._append_report_filters(filters, plan, "fs", parameters)
        self._append_where(sql, filters)
        self._append_order(
            sql, plan,
            {
                "company_code": "c.company_code", "report_date": "fs.report_date",
                "item_code": "fs.item_code", "value": "fs.value",
            },
            default="c.company_code ASC, fs.report_date ASC, fs.item_code ASC",
        )
        parameters["limit"] = plan.limit
        sql.append("LIMIT :limit")
        return self._result(
            plan, sql, parameters, select_columns,
            ("financial_statements", "companies", *tables),
        )

    def _compile_indicators(
        self, plan: StructuredQueryPlan, resolved: ResolvedPlanMetrics,
    ) -> CompiledQuery:
        parameters: dict[str, SQLParameter] = {}
        select_columns = (
            "company_code", "legal_name", "report_date", "period_type",
            "indicator_code", "indicator_name", "value", "unit", "calculation_method",
        )
        sql = [
            "SELECT c.company_code, c.legal_name, fi.report_date, fi.period_type,",
            "       fi.indicator_code, fi.indicator_name, fi.value, fi.unit,",
            "       fi.calculation_method",
            "FROM financial_indicators AS fi",
            "JOIN companies AS c ON c.id = fi.company_id",
        ]
        joins, filters, tables = self._entity_clauses(plan, parameters)
        sql.extend(joins)
        filters.append(self._in_clause(
            "fi.indicator_code", "metric_code",
            [item.code for item in resolved.metrics], parameters,
        ))
        self._append_report_filters(filters, plan, "fi", parameters)
        self._append_where(sql, filters)
        self._append_order(
            sql, plan,
            {
                "company_code": "c.company_code", "report_date": "fi.report_date",
                "indicator_code": "fi.indicator_code", "value": "fi.value",
            },
            default="c.company_code ASC, fi.report_date ASC, fi.indicator_code ASC",
        )
        parameters["limit"] = plan.limit
        sql.append("LIMIT :limit")
        return self._result(
            plan, sql, parameters, select_columns,
            ("financial_indicators", "companies", *tables),
        )

    def _compile_market(
        self, plan: StructuredQueryPlan, resolved: ResolvedPlanMetrics,
    ) -> CompiledQuery:
        parameters: dict[str, SQLParameter] = {}
        aggregate = any(item.aggregation != AggregationType.NONE for item in resolved.metrics)
        if aggregate and any(item.aggregation == AggregationType.NONE for item in resolved.metrics):
            raise QueryCompilationError("market query cannot mix raw and aggregated metrics")
        base_columns = ["company_code", "legal_name", "exchange", "ticker", "currency"]
        select_sql = [
            "c.company_code", "c.legal_name", "s.exchange", "s.ticker", "s.currency",
        ]
        metric_order: dict[str, str] = {}
        for metric in resolved.metrics:
            if metric.aggregation == AggregationType.NONE:
                expression = f"mp.{metric.value_column}"
                alias = metric.code
            else:
                function = _AGGREGATE_SQL[metric.aggregation]
                alias = f"{metric.aggregation.value}_{metric.code}"
                expression = f"{function}(mp.{metric.value_column})"
            select_sql.append(f"{expression} AS {alias}")
            base_columns.append(alias)
            metric_order[metric.code] = alias if aggregate else f"mp.{metric.value_column}"
        if not aggregate:
            select_sql.insert(5, "mp.trade_date")
            base_columns.insert(5, "trade_date")
        sql = [
            "SELECT " + ", ".join(select_sql),
            "FROM market_prices AS mp",
            "JOIN securities AS s ON s.id = mp.security_id",
            "JOIN companies AS c ON c.id = s.company_id",
        ]
        _, filters, _ = self._entity_clauses(plan, parameters, market=True)
        assert plan.time.start_date is not None and plan.time.end_date is not None
        parameters["start_date"] = plan.time.start_date
        parameters["end_date"] = plan.time.end_date
        filters.extend(("mp.trade_date >= :start_date", "mp.trade_date <= :end_date"))
        self._append_where(sql, filters)
        if aggregate:
            sql.append(
                "GROUP BY c.company_code, c.legal_name, s.exchange, s.ticker, s.currency"
            )
        order_allowlist = {
            "company_code": "c.company_code", "ticker": "s.ticker",
            "trade_date": "mp.trade_date", **metric_order,
        }
        default = "c.company_code ASC, s.ticker ASC"
        if not aggregate:
            default += ", mp.trade_date ASC"
        self._append_order(sql, plan, order_allowlist, default=default)
        parameters["limit"] = plan.limit
        sql.append("LIMIT :limit")
        return self._result(
            plan, sql, parameters, tuple(base_columns),
            ("market_prices", "securities", "companies"),
        )

    def _entity_clauses(
        self,
        plan: StructuredQueryPlan,
        parameters: dict[str, SQLParameter],
        *,
        company_only: bool = False,
        market: bool = False,
    ) -> tuple[list[str], list[str], tuple[str, ...]]:
        joins: list[str] = []
        filters: list[str] = []
        tables: list[str] = []
        entity = plan.entities
        if entity.company_codes:
            filters.append(self._in_clause(
                "c.company_code", "company_code", entity.company_codes, parameters,
            ))
        if entity.company_names:
            filters.append(self._in_clause(
                "c.legal_name", "company_name", entity.company_names, parameters,
            ))
        needs_security = bool(entity.tickers or entity.exchanges)
        if needs_security and not market:
            joins.append("JOIN securities AS s ON s.company_id = c.id")
            tables.append("securities")
        if entity.tickers:
            filters.append(self._in_clause("s.ticker", "ticker", entity.tickers, parameters))
        if entity.exchanges:
            filters.append(self._in_clause(
                "s.exchange", "exchange", entity.exchanges, parameters,
            ))
        if company_only and needs_security:
            return joins, filters, tuple(tables)
        return joins, filters, tuple(tables)

    def _append_report_filters(
        self,
        filters: list[str],
        plan: StructuredQueryPlan,
        alias: str,
        parameters: dict[str, SQLParameter],
    ) -> None:
        filters.append(self._in_clause(
            f"EXTRACT(YEAR FROM {alias}.report_date)", "report_year",
            plan.time.report_years, parameters,
        ))
        if plan.period_type is not None:
            parameters["period_type"] = plan.period_type.value
            filters.append(f"{alias}.period_type = :period_type")

    @staticmethod
    def _in_clause(
        field: str,
        prefix: str,
        values: Iterable[SQLParameter],
        parameters: dict[str, SQLParameter],
    ) -> str:
        placeholders: list[str] = []
        for index, value in enumerate(values):
            name = f"{prefix}_{index}"
            if name in parameters:
                raise QueryCompilationError(f"duplicate SQL parameter name: {name}")
            parameters[name] = value
            placeholders.append(f":{name}")
        if not placeholders:
            raise QueryCompilationError(f"cannot build empty IN clause for {field}")
        return f"{field} IN ({', '.join(placeholders)})"

    @staticmethod
    def _append_where(sql: list[str], filters: list[str]) -> None:
        if filters:
            sql.append("WHERE " + "\n  AND ".join(filters))

    @staticmethod
    def _append_order(
        sql: list[str],
        plan: StructuredQueryPlan,
        allowlist: dict[str, str],
        *,
        default: str,
    ) -> None:
        if not plan.order_by:
            sql.append(f"ORDER BY {default}")
            return
        clauses: list[str] = []
        for order in plan.order_by:
            expression = allowlist.get(order.field)
            if expression is None:
                raise QueryCompilationError(
                    f"order field '{order.field}' is not allowed for {plan.intent.value}"
                )
            direction = "ASC" if order.direction == SortDirection.ASCENDING else "DESC"
            clauses.append(f"{expression} {direction}")
        sql.append("ORDER BY " + ", ".join(clauses))

    @staticmethod
    def _result(
        plan: StructuredQueryPlan,
        sql: list[str],
        parameters: dict[str, SQLParameter],
        selected_columns: tuple[str, ...],
        source_tables: tuple[str, ...],
    ) -> CompiledQuery:
        return CompiledQuery(
            query_sha256=plan.query_sha256,
            sql="\n".join(sql), parameters=parameters,
            selected_columns=selected_columns,
            source_tables=tuple(dict.fromkeys(source_tables)), max_rows=plan.limit,
        )
