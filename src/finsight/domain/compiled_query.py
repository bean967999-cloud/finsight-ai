"""Serializable parameterized SQL artifact produced from a reviewed plan."""

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

SQLParameter = str | int | date
_PLACEHOLDER = re.compile(r"(?<!:):([a-z][a-z0-9_]*)")


class CompiledQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sql: str = Field(min_length=1)
    parameters: dict[str, SQLParameter]
    selected_columns: tuple[str, ...] = Field(min_length=1)
    source_tables: tuple[str, ...] = Field(min_length=1)
    max_rows: int = Field(ge=1, le=500)

    @model_validator(mode="after")
    def validate_parameters(self) -> "CompiledQuery":
        placeholders = set(_PLACEHOLDER.findall(self.sql))
        if placeholders != set(self.parameters):
            raise ValueError("SQL placeholders and parameters must match exactly")
        if ";" in self.sql:
            raise ValueError("compiled query must contain one statement without semicolon")
        if len(self.selected_columns) != len(set(self.selected_columns)):
            raise ValueError("selected column names must be unique")
        if len(self.source_tables) != len(set(self.source_tables)):
            raise ValueError("source tables must be unique")
        return self
