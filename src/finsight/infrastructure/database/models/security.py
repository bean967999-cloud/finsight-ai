from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import SecurityType, enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.company import Company
    from finsight.infrastructure.database.models.market_price import MarketPrice


class Security(TimestampMixin, Base):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("exchange", "ticker"),
        Index("ix_securities_company_id", "company_id"),
        Index("ix_securities_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    security_type: Mapped[SecurityType] = mapped_column(
        Enum(SecurityType, native_enum=False, length=16, values_callable=enum_values),
        default=SecurityType.STOCK,
        server_default=SecurityType.STOCK.value,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), default="CNY", server_default="CNY")
    listing_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    company: Mapped["Company"] = relationship(back_populates="securities")
    market_prices: Mapped[list["MarketPrice"]] = relationship(back_populates="security")
