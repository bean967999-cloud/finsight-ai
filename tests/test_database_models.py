from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import (
    Company,
    DataSource,
    FinancialIndicator,
    FinancialStatement,
    ImportJob,
    MarketPrice,
    Security,
)

EXPECTED_TABLES = {
    "companies",
    "securities",
    "market_prices",
    "financial_statements",
    "financial_indicators",
    "data_sources",
    "import_jobs",
}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_all_day_two_tables_are_registered():
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_all_models_share_the_same_declarative_metadata():
    models = (
        Company,
        Security,
        MarketPrice,
        FinancialStatement,
        FinancialIndicator,
        DataSource,
        ImportJob,
    )
    assert all(model.metadata is Base.metadata for model in models)
    configure_mappers()


def test_security_business_key_is_unique():
    assert ("exchange", "ticker") in _unique_column_sets("securities")


def test_market_price_versioned_business_key_is_unique():
    assert (
        "security_id",
        "trade_date",
        "adjustment_type",
        "data_source_id",
        "data_version",
    ) in _unique_column_sets("market_prices")


def test_financial_data_keeps_source_and_version_in_business_keys():
    statement_keys = _unique_column_sets("financial_statements")
    indicator_keys = _unique_column_sets("financial_indicators")

    assert any("data_source_id" in key and "data_version" in key for key in statement_keys)
    assert any("data_source_id" in key and "data_version" in key for key in indicator_keys)


def test_import_job_idempotency_key_is_unique():
    assert ("idempotency_key",) in _unique_column_sets("import_jobs")


def test_market_price_has_financial_sanity_checks():
    checks = {
        constraint.name
        for constraint in Base.metadata.tables["market_prices"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_market_prices_close_price_positive" in checks
    assert "ck_market_prices_high_not_below_low" in checks
    assert "ck_market_prices_volume_non_negative" in checks


def test_foreign_keys_protect_financial_lineage():
    assert Company.__table__.c.id.primary_key
    assert Security.__table__.c.company_id.foreign_keys
    assert MarketPrice.__table__.c.security_id.foreign_keys
    assert MarketPrice.__table__.c.data_source_id.foreign_keys
    assert FinancialStatement.__table__.c.company_id.foreign_keys
    assert FinancialIndicator.__table__.c.company_id.foreign_keys
    assert ImportJob.__table__.c.data_source_id.foreign_keys


def test_all_tables_have_audit_timestamps():
    for table_name in EXPECTED_TABLES:
        columns = Base.metadata.tables[table_name].c
        assert "created_at" in columns
        assert "updated_at" in columns


def test_enums_persist_stable_business_values():
    assert Company.__table__.c.status.type.enums == ["active", "inactive"]
    assert Security.__table__.c.security_type.type.enums == ["stock", "fund", "bond", "index"]
    assert ImportJob.__table__.c.status.type.enums == [
        "pending",
        "running",
        "succeeded",
        "failed",
    ]
