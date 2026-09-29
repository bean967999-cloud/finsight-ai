from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models import MarketPrice
from finsight.infrastructure.database.repositories.base import BaseRepository


class MarketPriceRepository(BaseRepository[MarketPrice]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MarketPrice)

    def get_by_business_key(
        self,
        security_id: int,
        trade_date: date,
        adjustment_type: str,
        data_source_id: int,
        data_version: int,
    ) -> MarketPrice | None:
        statement = select(MarketPrice).where(
            MarketPrice.security_id == security_id,
            MarketPrice.trade_date == trade_date,
            MarketPrice.adjustment_type == adjustment_type,
            MarketPrice.data_source_id == data_source_id,
            MarketPrice.data_version == data_version,
        )
        return self.session.scalar(statement)

    def list_by_security(
        self,
        security_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        adjustment_type: str = "none",
        limit: int = 500,
    ) -> list[MarketPrice]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must not be after end_date")

        statement = select(MarketPrice).where(
            MarketPrice.security_id == security_id,
            MarketPrice.adjustment_type == adjustment_type,
        )
        if start_date:
            statement = statement.where(MarketPrice.trade_date >= start_date)
        if end_date:
            statement = statement.where(MarketPrice.trade_date <= end_date)

        statement = statement.order_by(MarketPrice.trade_date).limit(limit)
        return list(self.session.scalars(statement))
