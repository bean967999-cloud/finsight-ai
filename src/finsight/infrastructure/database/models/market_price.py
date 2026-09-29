from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.data_source import DataSource
    from finsight.infrastructure.database.models.security import Security


class MarketPrice(TimestampMixin, Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "trade_date",
            "adjustment_type",
            "data_source_id",
            "data_version",
        ),
        CheckConstraint("open_price > 0", name="open_price_positive"),
        CheckConstraint("high_price > 0", name="high_price_positive"),
        CheckConstraint("low_price > 0", name="low_price_positive"),
        CheckConstraint("close_price > 0", name="close_price_positive"),
        CheckConstraint("high_price >= low_price", name="high_not_below_low"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        Index("ix_market_prices_security_trade_date", "security_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    adjustment_type: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", nullable=False
    )
    data_version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    security: Mapped["Security"] = relationship(back_populates="market_prices")
    data_source: Mapped["DataSource"] = relationship(back_populates="market_prices")
