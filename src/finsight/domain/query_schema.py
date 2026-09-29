"""Curated schema context exposed to structured financial querying."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QueryDataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    BOOLEAN = "boolean"


class QueryColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    data_type: QueryDataType
    description: str = Field(min_length=1, max_length=300)
    nullable: bool = False
    selectable: bool = True
    filterable: bool = True
    groupable: bool = False
    orderable: bool = False
    unit: str | None = Field(default=None, min_length=1, max_length=100)
    allowed_values: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_values(self) -> "QueryColumn":
        if len(self.allowed_values) != len(set(self.allowed_values)):
            raise ValueError("allowed_values must be unique")
        if self.allowed_values and self.data_type != QueryDataType.STRING:
            raise ValueError("allowed_values are only supported for string columns")
        return self


class QueryTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=500)
    columns: tuple[QueryColumn, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_columns(self) -> "QueryTable":
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("query table column names must be unique")
        if not any(column.selectable for column in self.columns):
            raise ValueError("query table needs at least one selectable column")
        return self


class QueryRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    cardinality: str = Field(pattern=r"^(many-to-one|one-to-many|one-to-one)$")
    description: str = Field(min_length=1, max_length=300)


class QuerySchemaContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    dialect: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    tables: tuple[QueryTable, ...] = Field(min_length=1)
    relationships: tuple[QueryRelationship, ...] = ()

    @model_validator(mode="after")
    def validate_context(self) -> "QuerySchemaContext":
        tables = {table.name: table for table in self.tables}
        if len(tables) != len(self.tables):
            raise ValueError("query table names must be unique")
        relationship_keys: set[tuple[str, str, str, str]] = set()
        for relationship in self.relationships:
            left = tables.get(relationship.left_table)
            right = tables.get(relationship.right_table)
            if left is None or right is None:
                raise ValueError("relationship references an unknown table")
            if relationship.left_column not in {column.name for column in left.columns}:
                raise ValueError("relationship references an unknown left column")
            if relationship.right_column not in {column.name for column in right.columns}:
                raise ValueError("relationship references an unknown right column")
            key = (
                relationship.left_table, relationship.left_column,
                relationship.right_table, relationship.right_column,
            )
            if key in relationship_keys:
                raise ValueError("query relationships must be unique")
            relationship_keys.add(key)
        return self

    def table(self, name: str) -> QueryTable:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(f"table is not exposed in query schema: {name}")
