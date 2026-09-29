from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from finsight.domain.query_execution import GuardedQuery
from finsight.domain.query_plan import (
    EntitySelection,
    MetricRequest,
    PlanStatus,
    QueryIntent,
    TimeSelection,
)
from finsight.services.metric_resolution import MetricResolver
from finsight.services.query_compiler import QueryCompiler
from finsight.services.query_planning import build_query_plan
from finsight.services.read_only_query_executor import QueryExecutionError, ReadOnlyQueryExecutor


def compiled_statement():
    plan = build_query_plan(
        "查询营业收入", status=PlanStatus.READY,
        intent=QueryIntent.FINANCIAL_STATEMENT,
        entities=EntitySelection(company_codes=("CMB",)),
        metrics=(MetricRequest(term="营业收入"),),
        time=TimeSelection(report_years=(2024,)), limit=20,
    )
    return QueryCompiler().compile(plan, MetricResolver().resolve_plan(plan))


class FakeResult:
    def __init__(self, columns, rows) -> None:
        self._columns = columns
        self._rows = rows

    def keys(self):
        return self._columns

    def mappings(self):
        return self

    def fetchmany(self, size):
        return self._rows[:size]


class FakeSession:
    def __init__(self, compiled, rows, *, columns=None, dialect="postgresql") -> None:
        self.compiled = compiled
        self.rows = rows
        self.columns = columns or compiled.selected_columns
        self.commands: list[tuple[str, object]] = []
        self.dialect = dialect

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        return nullcontext()

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.commands.append((sql, parameters))
        if sql == self.compiled.sql:
            return FakeResult(self.columns, self.rows)
        return FakeResult((), ())


def guarded_query() -> GuardedQuery:
    compiled = compiled_statement()
    return GuardedQuery(
        compiled=compiled, normalized_sql=compiled.sql,
        verified_tables=compiled.source_tables, verified_columns=("financial_statements.value",),
    )


def test_executor_sets_read_only_timeout_and_enforces_result_contract() -> None:
    guarded = guarded_query()
    row = {column: None for column in guarded.compiled.selected_columns}
    session = FakeSession(guarded.compiled, [row])
    result = ReadOnlyQueryExecutor(lambda: session, statement_timeout_ms=2500).execute(guarded)  # type: ignore[arg-type]
    assert session.commands[0][0] == "SET TRANSACTION READ ONLY"
    assert session.commands[1][0] == "SET LOCAL statement_timeout = 2500"
    assert session.commands[2][1] == guarded.compiled.parameters
    assert result.row_count == 1 and result.columns == guarded.compiled.selected_columns
    assert result.sql_sha256 != guarded.compiled.query_sha256


def test_executor_rejects_wrong_dialect_columns_and_excess_rows() -> None:
    guarded = guarded_query()
    with pytest.raises(QueryExecutionError, match="requires PostgreSQL"):
        ReadOnlyQueryExecutor(
            lambda: FakeSession(guarded.compiled, [], dialect="sqlite")  # type: ignore[arg-type]
        ).execute(guarded)
    with pytest.raises(QueryExecutionError, match="result columns"):
        ReadOnlyQueryExecutor(
            lambda: FakeSession(guarded.compiled, [], columns=("wrong",))  # type: ignore[arg-type]
        ).execute(guarded)
    rows = [
        {column: None for column in guarded.compiled.selected_columns}
        for _ in range(guarded.compiled.max_rows + 1)
    ]
    with pytest.raises(QueryExecutionError, match="more rows"):
        ReadOnlyQueryExecutor(
            lambda: FakeSession(guarded.compiled, rows)  # type: ignore[arg-type]
        ).execute(guarded)
