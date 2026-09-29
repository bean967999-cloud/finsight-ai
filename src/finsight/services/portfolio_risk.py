"""Long-only, fixed-weight portfolio risk over shared return windows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from finsight.domain.return_series import PriceSeries, calculate_return_windows


@dataclass(frozen=True)
class PortfolioPosition:
    prices: PriceSeries
    weight: float


@dataclass(frozen=True)
class PortfolioReturnPoint:
    period_start: date
    period_end: date
    value: float


@dataclass(frozen=True)
class RiskContribution:
    ticker: str
    annualized_volatility_contribution: float
    share_of_portfolio_volatility: float | None


@dataclass(frozen=True)
class PortfolioRiskResult:
    tickers: tuple[str, ...]
    weights: tuple[float, ...]
    adjustment_type: str
    aligned_observations: int
    trading_days_per_year: int
    returns: tuple[PortfolioReturnPoint, ...]
    covariance_matrix: tuple[tuple[float, ...], ...]
    correlation_matrix: tuple[tuple[float | None, ...], ...]
    annualized_mean_return: float
    daily_volatility: float
    annualized_volatility: float
    risk_contributions: tuple[RiskContribution, ...]


def calculate_portfolio_risk(
    positions: tuple[PortfolioPosition, ...], *, trading_days_per_year: int = 252
) -> PortfolioRiskResult:
    """Use sample covariance and assume target weights are restored each period."""
    if not positions:
        raise ValueError("at least one portfolio position is required")
    if trading_days_per_year < 1:
        raise ValueError("trading_days_per_year must be positive")

    tickers = tuple(position.prices.ticker for position in positions)
    weights = tuple(position.weight for position in positions)
    if len(set(tickers)) != len(tickers):
        raise ValueError("portfolio tickers must be unique")
    if any(not math.isfinite(weight) or not 0 <= weight <= 1 for weight in weights):
        raise ValueError("portfolio weights must be finite and between 0 and 1")
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("portfolio weights must sum to 1")
    adjustments = {position.prices.adjustment_type for position in positions}
    if len(adjustments) != 1:
        raise ValueError("portfolio adjustment types must match")

    windows_by_asset = [calculate_return_windows(position.prices) for position in positions]
    shared_windows = sorted(set.intersection(*(set(windows) for windows in windows_by_asset)))
    if len(shared_windows) < 2:
        raise ValueError("at least 2 shared return windows are required")

    values_by_asset = [
        [windows[period] for period in shared_windows] for windows in windows_by_asset
    ]
    count = len(shared_windows)
    means = [math.fsum(values) / count for values in values_by_asset]
    covariance = tuple(
        tuple(
            math.fsum(
                (left - means[row]) * (right - means[column])
                for left, right in zip(values_by_asset[row], values_by_asset[column], strict=True)
            )
            / (count - 1)
            for column in range(len(positions))
        )
        for row in range(len(positions))
    )
    if any(not math.isfinite(value) for row in covariance for value in row):
        raise ValueError("portfolio covariance is not finite")
    standard_deviations = [math.sqrt(covariance[index][index]) for index in range(len(positions))]
    correlation = tuple(
        tuple(
            max(
                -1.0,
                min(
                    1.0,
                    covariance[row][column]
                    / (standard_deviations[row] * standard_deviations[column]),
                ),
            )
            if standard_deviations[row] > 0 and standard_deviations[column] > 0
            else None
            for column in range(len(positions))
        )
        for row in range(len(positions))
    )

    returns = tuple(
        PortfolioReturnPoint(
            period_start=period[0],
            period_end=period[1],
            value=math.fsum(
                weight * values_by_asset[index][period_index]
                for index, weight in enumerate(weights)
            ),
        )
        for period_index, period in enumerate(shared_windows)
    )
    portfolio_mean = math.fsum(point.value for point in returns) / count
    daily_variance = math.fsum(
        (point.value - portfolio_mean) ** 2 for point in returns
    ) / (count - 1)
    daily_volatility = math.sqrt(daily_variance)
    annual_factor = math.sqrt(trading_days_per_year)
    annualized_volatility = daily_volatility * annual_factor
    annualized_mean_return = portfolio_mean * trading_days_per_year
    if not all(
        math.isfinite(value)
        for value in (annualized_volatility, annualized_mean_return)
    ):
        raise ValueError("portfolio risk result is not finite")

    risk_contributions = tuple(
        RiskContribution(
            ticker=ticker,
            annualized_volatility_contribution=(
                weight
                * math.fsum(covariance[index][column] * weights[column] for column in range(len(weights)))
                / daily_volatility
                * annual_factor
                if daily_volatility > 0
                else 0.0
            ),
            share_of_portfolio_volatility=(
                weight
                * math.fsum(covariance[index][column] * weights[column] for column in range(len(weights)))
                / daily_variance
                if daily_variance > 0
                else None
            ),
        )
        for index, (ticker, weight) in enumerate(zip(tickers, weights, strict=True))
    )

    return PortfolioRiskResult(
        tickers=tickers,
        weights=weights,
        adjustment_type=next(iter(adjustments)),
        aligned_observations=count,
        trading_days_per_year=trading_days_per_year,
        returns=returns,
        covariance_matrix=covariance,
        correlation_matrix=correlation,
        annualized_mean_return=annualized_mean_return,
        daily_volatility=daily_volatility,
        annualized_volatility=annualized_volatility,
        risk_contributions=risk_contributions,
    )
