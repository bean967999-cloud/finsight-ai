"""Risk-adjusted return and benchmark sensitivity for dated prices."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from finsight.domain.return_series import (
    PriceSeries,
    calculate_return_windows,
    calculate_returns,
)
from finsight.services.price_risk import calculate_volatility


@dataclass(frozen=True)
class SharpeResult:
    observations: int
    trading_days_per_year: int
    annual_risk_free_rate: float
    risk_free_rate_per_period: float
    annualized_mean_return: float
    annualized_volatility: float
    sharpe_ratio: float | None


@dataclass(frozen=True)
class BetaResult:
    asset_ticker: str
    benchmark_ticker: str
    aligned_observations: int
    first_period_end: date
    last_period_end: date
    beta: float | None


def calculate_sharpe(
    prices: PriceSeries,
    *,
    annual_risk_free_rate: float = 0.0,
    trading_days_per_year: int = 252,
) -> SharpeResult:
    """Annualized arithmetic excess return divided by sample volatility."""
    if not math.isfinite(annual_risk_free_rate) or annual_risk_free_rate <= -1:
        raise ValueError("annual_risk_free_rate must be finite and greater than -1")
    if trading_days_per_year < 1:
        raise ValueError("trading_days_per_year must be positive")

    returns = [point.value for point in calculate_returns(prices).points]
    volatility = calculate_volatility(prices, trading_days_per_year=trading_days_per_year)
    mean_return = math.fsum(returns) / len(returns)
    risk_free_per_period = math.expm1(
        math.log1p(annual_risk_free_rate) / trading_days_per_year
    )
    annualized_mean_return = mean_return * trading_days_per_year
    if not math.isfinite(annualized_mean_return):
        raise ValueError("annualized mean return is not finite")

    sharpe = None
    if volatility.daily_volatility > 0:
        sharpe = (
            (mean_return - risk_free_per_period)
            / volatility.daily_volatility
            * math.sqrt(trading_days_per_year)
        )
        if not math.isfinite(sharpe):
            raise ValueError("sharpe ratio is not finite")

    return SharpeResult(
        observations=len(returns),
        trading_days_per_year=trading_days_per_year,
        annual_risk_free_rate=annual_risk_free_rate,
        risk_free_rate_per_period=risk_free_per_period,
        annualized_mean_return=annualized_mean_return,
        annualized_volatility=volatility.annualized_volatility,
        sharpe_ratio=sharpe,
    )


def calculate_beta(asset: PriceSeries, benchmark: PriceSeries) -> BetaResult:
    """Regression slope of asset returns against matching benchmark windows."""
    asset_windows = calculate_return_windows(asset)
    benchmark_windows = calculate_return_windows(benchmark)
    shared_windows = sorted(asset_windows.keys() & benchmark_windows.keys())
    if len(shared_windows) < 2:
        raise ValueError("at least 2 matching return windows are required for beta")

    asset_values = [asset_windows[window] for window in shared_windows]
    benchmark_values = [benchmark_windows[window] for window in shared_windows]
    asset_mean = math.fsum(asset_values) / len(asset_values)
    benchmark_mean = math.fsum(benchmark_values) / len(benchmark_values)
    benchmark_squared = math.fsum(
        (value - benchmark_mean) ** 2 for value in benchmark_values
    )

    beta = None
    if benchmark_squared > 0:
        cross_product = math.fsum(
            (asset_value - asset_mean) * (benchmark_value - benchmark_mean)
            for asset_value, benchmark_value in zip(asset_values, benchmark_values, strict=True)
        )
        beta = cross_product / benchmark_squared
        if not math.isfinite(beta):
            raise ValueError("beta is not finite")

    return BetaResult(
        asset_ticker=asset.ticker,
        benchmark_ticker=benchmark.ticker,
        aligned_observations=len(shared_windows),
        first_period_end=shared_windows[0][1],
        last_period_end=shared_windows[-1][1],
        beta=beta,
    )
