from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import CompanyStatus, enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.financial_indicator import FinancialIndicator
    from finsight.infrastructure.database.models.financial_statement import FinancialStatement
    from finsight.infrastructure.database.models.security import Security


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_legal_name", "legal_name"),
        Index("ix_companies_industry", "industry"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100))
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    industry: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="CN", server_default="CN")
    established_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus, native_enum=False, length=16, values_callable=enum_values),
        default=CompanyStatus.ACTIVE,
        server_default=CompanyStatus.ACTIVE.value,
        nullable=False,
    )

    securities: Mapped[list["Security"]] = relationship(back_populates="company")
    financial_statements: Mapped[list["FinancialStatement"]] = relationship(
        back_populates="company"
    )
    financial_indicators: Mapped[list["FinancialIndicator"]] = relationship(
        back_populates="company"
    )
