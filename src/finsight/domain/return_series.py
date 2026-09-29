"""Dated price and return contracts for deterministic risk calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class ReturnMethod(StrEnum):
    SIMPLE = "simple"
    LOG = "log"


@dataclass(frozen=True)
class PricePoint:
    trade_date: date
    close_price: Decimal


@dataclass(frozen=True)
class PriceSeries:
    ticker: str
    adjustment_type: str
    data_source: str
    data_version: int
    points: tuple[PricePoint, ...]

    def __post_init__(self) -> None:
        if not self.ticker.strip() or not self.adjustment_type.strip():
            raise ValueError("ticker and adjustment_type are required")
        if not self.data_source.strip() or self.data_version < 1:
            raise ValueError("data_source and positive data_version are required")
        if len(self.points) < 2:
            raise ValueError("at least 2 dated prices are required")

        previous_date: date | None = None
        for point in self.points:
            if previous_date is not None and point.trade_date <= previous_date:
                raise ValueError("trade dates must be strictly increasing and unique")
            if not point.close_price.is_finite() or point.close_price <= 0:
                raise ValueError("close prices must be finite and positive")
            previous_date = point.trade_date


@dataclass(frozen=True)
class ReturnPoint:
    trade_date: date
    value: float


@dataclass(frozen=True)
class ReturnSeries:
    ticker: str
    adjustment_type: str
    data_source: str
    data_version: int
    method: ReturnMethod
    points: tuple[ReturnPoint, ...]


def calculate_returns(
    prices: PriceSeries, method: ReturnMethod = ReturnMethod.SIMPLE
) -> ReturnSeries:
    """Calculate each return against the previous observed trading date.

    Missing calendar dates are not filled: holidays and missing market data
    cannot be distinguished from this series alone.
    """
    if not isinstance(method, ReturnMethod):
        raise TypeError("unsupported return method")

    observations: list[ReturnPoint] = []
    for previous, current in zip(prices.points, prices.points[1:], strict=False):
        ratio = float(current.close_price / previous.close_price)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("price ratio must be finite and positive")
        value = ratio - 1.0 if method is ReturnMethod.SIMPLE else math.log(ratio)
        observations.append(ReturnPoint(trade_date=current.trade_date, value=value))

    return ReturnSeries(
        ticker=prices.ticker,
        adjustment_type=prices.adjustment_type,
        data_source=prices.data_source,
        data_version=prices.data_version,
        method=method,
        points=tuple(observations),
    )


def calculate_return_windows(prices: PriceSeries) -> dict[tuple[date, date], float]:
    """Index simple returns by both interval endpoints for exact alignment."""
    returns = calculate_returns(prices).points
    return {
        (previous.trade_date, current.trade_date): point.value
        for previous, current, point in zip(
            prices.points[:-1], prices.points[1:], returns, strict=True
        )
    }
