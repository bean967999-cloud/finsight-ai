"""Volatility and drawdown calculations over dated price observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from finsight.domain.return_series import PriceSeries, calculate_returns


@dataclass(frozen=True)
class VolatilityResult:
    return_observations: int
    trading_days_per_year: int
    daily_volatility: float
    annualized_volatility: float


@dataclass(frozen=True)
class WealthPoint:
    trade_date: date
    wealth_index: float
    drawdown: float


@dataclass(frozen=True)
class DrawdownResult:
    curve: tuple[WealthPoint, ...]
    max_drawdown: float
    peak_date: date | None
    trough_date: date | None


def calculate_volatility(
    prices: PriceSeries, *, trading_days_per_year: int = 252
) -> VolatilityResult:
    """Sample standard deviation of simple returns, scaled by sqrt(trading days)."""
    if trading_days_per_year < 1:
        raise ValueError("trading_days_per_year must be positive")

    returns = [point.value for point in calculate_returns(prices).points]
    if len(returns) < 2:
        raise ValueError("at least 3 prices are required for sample volatility")

    mean = math.fsum(returns) / len(returns)
    variance = math.fsum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    daily = math.sqrt(variance)
    annualized = daily * math.sqrt(trading_days_per_year)
    if not math.isfinite(annualized):
        raise ValueError("volatility is not finite")

    return VolatilityResult(
        return_observations=len(returns),
        trading_days_per_year=trading_days_per_year,
        daily_volatility=daily,
        annualized_volatility=annualized,
    )


def calculate_drawdown(prices: PriceSeries) -> DrawdownResult:
    """Track wealth from the first close and loss from the running peak."""
    first_price = prices.points[0].close_price
    running_peak = 1.0
    running_peak_date = prices.points[0].trade_date
    max_drawdown = 0.0
    peak_date: date | None = None
    trough_date: date | None = None
    curve: list[WealthPoint] = []

    for point in prices.points:
        wealth = float(point.close_price / first_price)
        if not math.isfinite(wealth) or wealth <= 0:
            raise ValueError("wealth index must be finite and positive")
        if wealth > running_peak:
            running_peak = wealth
            running_peak_date = point.trade_date
        drawdown = wealth / running_peak - 1.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            peak_date = running_peak_date
            trough_date = point.trade_date
        curve.append(WealthPoint(point.trade_date, wealth, drawdown))

    return DrawdownResult(tuple(curve), max_drawdown, peak_date, trough_date)
