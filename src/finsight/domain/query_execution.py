"""Guarded query and read-only execution result contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.compiled_query import CompiledQuery


class GuardedQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    compiled: CompiledQuery
    normalized_sql: str
    verified_tables: tuple[str, ...]
    verified_columns: tuple[str, ...]


class QueryExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sql_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int = Field(ge=0)
    execution_ms: float = Field(ge=0)
