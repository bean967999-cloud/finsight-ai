"""PostgreSQL read-only execution with timeout and result-shape enforcement."""

from collections.abc import Callable
from hashlib import sha256
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.orm import Session

from finsight.domain.query_execution import GuardedQuery, QueryExecutionResult

SessionProvider = Callable[[], Session]


class QueryExecutionError(RuntimeError):
    pass


class ReadOnlyQueryExecutor:
    def __init__(
        self,
        session_provider: SessionProvider,
        *,
        statement_timeout_ms: int = 3_000,
    ) -> None:
        if not 100 <= statement_timeout_ms <= 30_000:
            raise ValueError("statement_timeout_ms must be between 100 and 30000")
        self._sessions = session_provider
        self._statement_timeout_ms = statement_timeout_ms

    def execute(self, guarded: GuardedQuery) -> QueryExecutionResult:
        compiled = guarded.compiled
        started = perf_counter()
        try:
            with self._sessions() as session, session.begin():
                dialect = session.get_bind().dialect.name
                if dialect != "postgresql":
                    raise QueryExecutionError("read-only query execution requires PostgreSQL")
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text(
                    f"SET LOCAL statement_timeout = {self._statement_timeout_ms}"
                ))
                result = session.execute(text(compiled.sql), compiled.parameters)
                columns = tuple(result.keys())
                if columns != compiled.selected_columns:
                    raise QueryExecutionError(
                        "database result columns do not match the compiled query contract"
                    )
                rows = tuple(dict(row) for row in result.mappings().fetchmany(compiled.max_rows + 1))
                if len(rows) > compiled.max_rows:
                    raise QueryExecutionError("database returned more rows than the approved limit")
        except QueryExecutionError:
            raise
        except Exception as exc:
            raise QueryExecutionError("read-only query execution failed") from exc
        return QueryExecutionResult(
            query_sha256=compiled.query_sha256,
            sql_sha256=sha256(compiled.sql.encode("utf-8")).hexdigest(),
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_ms=(perf_counter() - started) * 1000,
        )
