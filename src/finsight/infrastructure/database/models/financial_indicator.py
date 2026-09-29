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
from finsight.infrastructure.database.models.enums import ReportingPeriodType, enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.company import Company
    from finsight.infrastructure.database.models.data_source import DataSource


class FinancialIndicator(TimestampMixin, Base):
    __tablename__ = "financial_indicators"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "report_date",
            "period_type",
            "indicator_code",
            "data_source_id",
            "data_version",
        ),
        Index(
            "ix_financial_indicators_company_report_date",
            "company_id",
            "report_date",
        ),
        Index("ix_financial_indicators_indicator_code", "indicator_code"),
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
    indicator_code: Mapped[str] = mapped_column(String(100), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    calculation_method: Mapped[str | None] = mapped_column(String(500))
    data_version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship(back_populates="financial_indicators")
    data_source: Mapped["DataSource"] = relationship(back_populates="financial_indicators")
