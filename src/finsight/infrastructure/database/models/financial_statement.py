from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import (
    ReportingPeriodType,
    StatementType,
    enum_values,
)

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.company import Company
    from finsight.infrastructure.database.models.data_source import DataSource


class FinancialStatement(TimestampMixin, Base):
    __tablename__ = "financial_statements"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "report_date",
            "period_type",
            "statement_type",
            "item_code",
            "consolidation_scope",
            "data_source_id",
            "data_version",
        ),
        Index(
            "ix_financial_statements_company_report_date",
            "company_id",
            "report_date",
        ),
        Index("ix_financial_statements_item_code", "item_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[ReportingPeriodType] = mapped_column(
        Enum(
            ReportingPeriodType,
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    statement_type: Mapped[StatementType] = mapped_column(
        Enum(StatementType, native_enum=False, length=32, values_callable=enum_values),
        nullable=False,
    )
    item_code: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6))
    currency: Mapped[str] = mapped_column(String(3), default="CNY", server_default="CNY")
    unit: Mapped[str] = mapped_column(String(32), default="yuan", server_default="yuan")
    consolidation_scope: Mapped[str] = mapped_column(
        String(16), default="consolidated", server_default="consolidated", nullable=False
    )
    data_version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship(back_populates="financial_statements")
    data_source: Mapped["DataSource"] = relationship(back_populates="financial_statements")
