import pytest
from pydantic import ValidationError

from finsight.domain.query_schema import QueryRelationship, QuerySchemaContext
from finsight.services.query_schema_context import (
    build_financial_query_schema,
    render_query_schema,
)


def test_context_exposes_only_reviewed_business_tables_and_fields() -> None:
    context = build_financial_query_schema()
    assert [table.name for table in context.tables] == [
        "companies", "securities", "financial_statements",
        "financial_indicators", "market_prices",
    ]
    assert "unified_social_credit_code" not in {
        column.name for column in context.table("companies").columns
    }
    assert "data_sources" not in {table.name for table in context.tables}
    assert not next(
        column for column in context.table("companies").columns if column.name == "id"
    ).selectable


def test_units_period_values_and_relationships_are_explicit() -> None:
    context = build_financial_query_schema()
    statement_columns = {column.name: column for column in context.table("financial_statements").columns}
    assert statement_columns["value"].unit == "由 unit 与 currency 列共同决定"
    assert statement_columns["period_type"].allowed_values == (
        "annual", "semiannual", "quarterly",
    )
    assert statement_columns["statement_type"].allowed_values[-1] == "cash_flow_statement"
    assert any(
        relation.left_table == "market_prices"
        and relation.right_table == "securities"
        for relation in context.relationships
    )


def test_render_is_deterministic_and_contains_no_hidden_fields() -> None:
    context = build_financial_query_schema()
    first = render_query_schema(context)
    assert first == render_query_schema(context)
    assert "TABLE financial_statements" in first
    assert "market_prices.security_id -> securities.id" in first
    assert "unified_social_credit_code" not in first
    assert "ingested_at" not in first


def test_invalid_relationship_is_rejected() -> None:
    context = build_financial_query_schema()
    invalid = QueryRelationship(
        left_table="market_prices", left_column="missing_column",
        right_table="securities", right_column="id", cardinality="many-to-one",
        description="invalid fixture",
    )
    with pytest.raises(ValidationError, match="unknown left column"):
        QuerySchemaContext(
            version="v1", dialect="postgres", tables=context.tables,
            relationships=(*context.relationships, invalid),
        )
