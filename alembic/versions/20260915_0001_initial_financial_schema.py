"""Create the initial financial data schema.

Revision ID: 20260915_0001
Revises:
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_code", sa.String(length=32), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=100), nullable=True),
        sa.Column("unified_social_credit_code", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=2), server_default="CN", nullable=False),
        sa.Column("established_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "inactive",
                name="companystatus",
                native_enum=False,
                length=16,
            ),
            server_default="active",
            nullable=False,
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("company_code", name=op.f("uq_companies_company_code")),
        sa.UniqueConstraint(
            "unified_social_credit_code",
            name=op.f("uq_companies_unified_social_credit_code"),
        ),
    )
    op.create_index("ix_companies_industry", "companies", ["industry"], unique=False)
    op.create_index("ix_companies_legal_name", "companies", ["legal_name"], unique=False)

    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_sources")),
        sa.UniqueConstraint("code", name=op.f("uq_data_sources_code")),
    )

    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "security_type",
            sa.Enum(
                "stock",
                "fund",
                "bond",
                "index",
                name="securitytype",
                native_enum=False,
                length=16,
            ),
            server_default="stock",
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("delisting_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_securities_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_securities")),
        sa.UniqueConstraint("exchange", "ticker", name=op.f("uq_securities_exchange_ticker")),
    )
    op.create_index("ix_securities_company_id", "securities", ["company_id"], unique=False)
    op.create_index("ix_securities_ticker", "securities", ["ticker"], unique=False)

    op.create_table(
        "financial_indicators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum(
                "annual",
                "semiannual",
                "quarterly",
                name="reportingperiodtype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("indicator_code", sa.String(length=100), nullable=False),
        sa.Column("indicator_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("calculation_method", sa.String(length=500), nullable=True),
        sa.Column("data_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_financial_indicators_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_sources.id"],
            name=op.f("fk_financial_indicators_data_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_indicators")),
        sa.UniqueConstraint(
            "company_id",
            "report_date",
            "period_type",
            "indicator_code",
            "data_source_id",
            "data_version",
            name=op.f(
                "uq_financial_indicators_company_id_report_date_period_type_"
                "indicator_code_data_source_id_data_version"
            ),
        ),
    )
    op.create_index(
        "ix_financial_indicators_company_report_date",
        "financial_indicators",
        ["company_id", "report_date"],
        unique=False,
    )
    op.create_index(
        "ix_financial_indicators_indicator_code",
        "financial_indicators",
        ["indicator_code"],
        unique=False,
    )

    op.create_table(
        "financial_statements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum(
                "annual",
                "semiannual",
                "quarterly",
                name="reportingperiodtype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "statement_type",
            sa.Enum(
                "balance_sheet",
                "income_statement",
                "cash_flow_statement",
                name="statementtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("item_code", sa.String(length=100), nullable=False),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("unit", sa.String(length=32), server_default="yuan", nullable=False),
        sa.Column(
            "consolidation_scope",
            sa.String(length=16),
            server_default="consolidated",
            nullable=False,
        ),
        sa.Column("data_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_financial_statements_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_sources.id"],
            name=op.f("fk_financial_statements_data_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_statements")),
        sa.UniqueConstraint(
            "company_id",
            "report_date",
            "period_type",
            "statement_type",
            "item_code",
            "consolidation_scope",
            "data_source_id",
            "data_version",
            name=op.f(
                "uq_financial_statements_company_id_report_date_period_type_statement_type_"
                "item_code_consolidation_scope_data_source_id_data_version"
            ),
        ),
    )
    op.create_index(
        "ix_financial_statements_company_report_date",
        "financial_statements",
        ["company_id", "report_date"],
        unique=False,
    )
    op.create_index(
        "ix_financial_statements_item_code",
        "financial_statements",
        ["item_code"],
        unique=False,
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "job_type",
            sa.Enum(
                "company",
                "security",
                "market_price",
                "financial_statement",
                "financial_indicator",
                name="importjobtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                name="importjobstatus",
                native_enum=False,
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_sources.id"],
            name=op.f("fk_import_jobs_data_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_import_jobs_idempotency_key")),
    )
    op.create_index(
        "ix_import_jobs_status_created_at",
        "import_jobs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "market_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open_price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("high_price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("low_price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("close_price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("volume", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("adjustment_type", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("data_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint("close_price > 0", name=op.f("ck_market_prices_close_price_positive")),
        sa.CheckConstraint("high_price > 0", name=op.f("ck_market_prices_high_price_positive")),
        sa.CheckConstraint("high_price >= low_price", name=op.f("ck_market_prices_high_not_below_low")),
        sa.CheckConstraint("low_price > 0", name=op.f("ck_market_prices_low_price_positive")),
        sa.CheckConstraint("open_price > 0", name=op.f("ck_market_prices_open_price_positive")),
        sa.CheckConstraint("volume >= 0", name=op.f("ck_market_prices_volume_non_negative")),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_sources.id"],
            name=op.f("fk_market_prices_data_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.id"],
            name=op.f("fk_market_prices_security_id_securities"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_prices")),
        sa.UniqueConstraint(
            "security_id",
            "trade_date",
            "adjustment_type",
            "data_source_id",
            "data_version",
            name=op.f(
                "uq_market_prices_security_id_trade_date_adjustment_type_"
                "data_source_id_data_version"
            ),
        ),
    )
    op.create_index(
        "ix_market_prices_security_trade_date",
        "market_prices",
        ["security_id", "trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_prices_security_trade_date", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_index("ix_import_jobs_status_created_at", table_name="import_jobs")
    op.drop_table("import_jobs")
    op.drop_index("ix_financial_statements_item_code", table_name="financial_statements")
    op.drop_index(
        "ix_financial_statements_company_report_date", table_name="financial_statements"
    )
    op.drop_table("financial_statements")
    op.drop_index("ix_financial_indicators_indicator_code", table_name="financial_indicators")
    op.drop_index(
        "ix_financial_indicators_company_report_date", table_name="financial_indicators"
    )
    op.drop_table("financial_indicators")
    op.drop_index("ix_securities_ticker", table_name="securities")
    op.drop_index("ix_securities_company_id", table_name="securities")
    op.drop_table("securities")
    op.drop_table("data_sources")
    op.drop_index("ix_companies_legal_name", table_name="companies")
    op.drop_index("ix_companies_industry", table_name="companies")
    op.drop_table("companies")
