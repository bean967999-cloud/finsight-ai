from __future__ import annotations

import sqlglot
from sqlglot import exp


class SQLGuardError(ValueError):
    pass


BLOCKED_NODE_KEYS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "merge",
    "command",
    "copy",
    "grant",
    "revoke",
}


def validate_read_only_sql(sql: str, max_rows: int = 500) -> str:
    """
    Parse SQL into an AST and only allow a single read-only query.

    This is only ONE layer of protection.
    Production also needs:
    - read-only DB role
    - schema/table allowlist
    - statement timeout
    - row limit
    - audit logs
    """
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1:
        raise SQLGuardError("only one SQL statement is allowed")

    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SQLGuardError("only read-only queries are allowed")
    root_key = getattr(tree, "key", "").lower()
    if root_key not in {"select", "union", "intersect", "except"}:
        raise SQLGuardError(f"statement type '{root_key}' is not allowed")

    for node in tree.walk():
        key = getattr(node, "key", "").lower()
        if key in BLOCKED_NODE_KEYS:
            raise SQLGuardError(f"dangerous SQL node '{key}' is not allowed")

    # Add a defensive LIMIT when the root query does not already contain one.
    if not tree.args.get("limit"):
        tree = tree.limit(max_rows)

    return tree.sql(dialect="postgres")
