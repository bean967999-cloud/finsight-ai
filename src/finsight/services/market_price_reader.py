"""Read one unambiguous market price series from PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.infrastructure.database.models import DataSource, MarketPrice, Security


class MarketPriceNotFound(ValueError):
    """No observations match an exact market data selection."""


@dataclass(frozen=True)
class MarketPriceSelection:
    exchange: str
    ticker: str
    source_code: str
    adjustment_type: str
    data_version: int
    start_date: date
    end_date: date


@dataclass(frozen=True)
class LoadedPriceSeries:
    prices: PriceSeries
    currency: str


class MarketPriceReader:
    def __init__(self, session_provider: Callable[[], Session]) -> None:
        self._session_provider = session_provider

    def load(self, selection: MarketPriceSelection) -> LoadedPriceSeries:
        if selection.start_date > selection.end_date:
            raise ValueError("start_date must not be after end_date")
        if selection.data_version < 1:
            raise ValueError("data_version must be positive")

        statement = (
            select(MarketPrice.trade_date, MarketPrice.close_price, Security.currency)
            .join(Security, MarketPrice.security_id == Security.id)
            .join(DataSource, MarketPrice.data_source_id == DataSource.id)
            .where(
                Security.exchange == selection.exchange,
                Security.ticker == selection.ticker,
                DataSource.code == selection.source_code,
                MarketPrice.adjustment_type == selection.adjustment_type,
                MarketPrice.data_version == selection.data_version,
                MarketPrice.trade_date >= selection.start_date,
                MarketPrice.trade_date <= selection.end_date,
            )
            .order_by(MarketPrice.trade_date)
            .limit(5002)
        )
        with self._session_provider() as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            rows = session.execute(statement).all()

        if not rows:
            raise MarketPriceNotFound("no market prices match the selected security and source")
        if len(rows) > 5001:
            raise ValueError("market price selection exceeds 5001 observations")
        prices = PriceSeries(
            ticker=selection.ticker,
            adjustment_type=selection.adjustment_type,
            data_source=selection.source_code,
            data_version=selection.data_version,
            points=tuple(PricePoint(row.trade_date, row.close_price) for row in rows),
        )
        return LoadedPriceSeries(prices=prices, currency=rows[0].currency)
