"""Defense-in-depth AST validation for compiled structured queries."""

import re

import sqlglot
from sqlglot import exp

from finsight.domain.compiled_query import CompiledQuery
from finsight.domain.query_execution import GuardedQuery
from finsight.domain.query_schema import QuerySchemaContext
from finsight.security.sql_guard import SQLGuardError, validate_read_only_sql

_ALLOWED_FUNCTIONS = {"avg", "min", "max", "sum", "extract"}
_FUNCTION_CALL = re.compile(r"^[A-Z_][A-Z0-9_]*\s*\(")


def guard_compiled_query(
    compiled: CompiledQuery,
    schema: QuerySchemaContext,
    *,
    max_joins: int = 3,
) -> GuardedQuery:
    if max_joins < 0:
        raise ValueError("max_joins must not be negative")
    if "--" in compiled.sql or "/*" in compiled.sql or "*/" in compiled.sql:
        raise SQLGuardError("SQL comments are not allowed")
    normalized = validate_read_only_sql(compiled.sql, max_rows=compiled.max_rows)
    tree = sqlglot.parse_one(normalized, read="postgres")
    if any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union, exp.Intersect, exp.Except)) for node in tree.walk()):
        raise SQLGuardError("subqueries, CTEs, and set operations are not allowed")
    if any(isinstance(node, exp.Star) for node in tree.walk()):
        raise SQLGuardError("SELECT * is not allowed")
    joins = list(tree.find_all(exp.Join))
    if len(joins) > max_joins:
        raise SQLGuardError(f"query exceeds maximum join count of {max_joins}")

    exposed_tables = {table.name: table for table in schema.tables}
    alias_to_table: dict[str, str] = {}
    actual_tables: list[str] = []
    for table_expression in tree.find_all(exp.Table):
        table_name = table_expression.name
        if table_name not in exposed_tables:
            raise SQLGuardError(f"table '{table_name}' is not in the query allowlist")
        alias = table_expression.alias_or_name or table_name
        if alias in alias_to_table and alias_to_table[alias] != table_name:
            raise SQLGuardError(f"table alias '{alias}' is reused")
        alias_to_table[alias] = table_name
        actual_tables.append(table_name)
    if set(actual_tables) != set(compiled.source_tables):
        raise SQLGuardError("actual SQL tables do not match compiled query source tables")

    verified_columns: list[str] = []
    output_aliases = set(compiled.selected_columns)
    for column in tree.find_all(exp.Column):
        if not column.table:
            if column.name not in output_aliases:
                raise SQLGuardError(f"unqualified column '{column.name}' is not an output alias")
            continue
        resolved_table = alias_to_table.get(column.table)
        if resolved_table is None:
            raise SQLGuardError(f"unknown table alias '{column.table}'")
        allowed_columns = {item.name for item in exposed_tables[resolved_table].columns}
        if column.name not in allowed_columns:
            raise SQLGuardError(
                f"column '{resolved_table}.{column.name}' is not in the query allowlist"
            )
        verified_columns.append(f"{resolved_table}.{column.name}")

    for function in tree.find_all(exp.Func):
        rendered = function.sql(dialect="postgres").lstrip().upper()
        if _FUNCTION_CALL.match(rendered) and function.key.lower() not in _ALLOWED_FUNCTIONS:
            raise SQLGuardError(f"function '{function.key}' is not allowed")

    limit = compiled.parameters.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise SQLGuardError("compiled LIMIT must be an integer parameter")
    if limit != compiled.max_rows or not 1 <= limit <= 500:
        raise SQLGuardError("compiled LIMIT does not match the approved row limit")
    return GuardedQuery(
        compiled=compiled,
        normalized_sql=normalized,
        verified_tables=tuple(dict.fromkeys(actual_tables)),
        verified_columns=tuple(dict.fromkeys(verified_columns)),
    )
