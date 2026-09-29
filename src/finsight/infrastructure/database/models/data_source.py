from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.financial_indicator import FinancialIndicator
    from finsight.infrastructure.database.models.financial_statement import FinancialStatement
    from finsight.infrastructure.database.models.import_job import ImportJob
    from finsight.infrastructure.database.models.market_price import MarketPrice


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    market_prices: Mapped[list["MarketPrice"]] = relationship(back_populates="data_source")
    financial_statements: Mapped[list["FinancialStatement"]] = relationship(
        back_populates="data_source"
    )
    financial_indicators: Mapped[list["FinancialIndicator"]] = relationship(
        back_populates="data_source"
    )
    import_jobs: Mapped[list["ImportJob"]] = relationship(back_populates="data_source")
