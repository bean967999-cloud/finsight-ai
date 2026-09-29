"""Historical simulation of value at risk and conditional value at risk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from finsight.domain.return_series import PriceSeries


@dataclass(frozen=True)
class HistoricalTailRisk:
    confidence: float
    holding_period: int
    observations: int
    tail_observations: int
    value_at_risk: float
    conditional_value_at_risk: float
    first_window_start: date
    last_window_end: date


def calculate_historical_tail_risk(
    prices: PriceSeries,
    *,
    confidence: float = 0.95,
    holding_period: int = 1,
    minimum_observations: int = 20,
) -> HistoricalTailRisk:
    """Use the worst ceil((1-confidence)*n) observed holding-period losses.

    Windows overlap when holding_period > 1. The result is a fraction of
    invested value, not a currency amount or a forecast guarantee.
    """
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be greater than 0.5 and less than 1")
    if not 1 <= holding_period <= 252:
        raise ValueError("holding_period must be between 1 and 252 observations")
    if minimum_observations < 2:
        raise ValueError("minimum_observations must be at least 2")

    confidence_decimal = Decimal(str(confidence))
    tail_probability = Decimal(1) - confidence_decimal
    required_for_tail = int(
        (Decimal(1) / tail_probability).to_integral_value(rounding=ROUND_CEILING)
    )
    count = len(prices.points) - holding_period
    required = max(minimum_observations, required_for_tail)
    if count < required:
        raise ValueError(
            f"at least {required} holding-period return observations are required; got {count}"
        )

    losses = sorted(
        (
            Decimal(1)
            - prices.points[index + holding_period].close_price
            / prices.points[index].close_price
            for index in range(count)
        ),
        reverse=True,
    )
    tail_count = int(
        (tail_probability * count).to_integral_value(rounding=ROUND_CEILING)
    )
    worst_losses = losses[:tail_count]
    value_at_risk = max(losses[tail_count - 1], Decimal(0))
    conditional_value_at_risk = max(
        sum(worst_losses, Decimal(0)) / tail_count, Decimal(0)
    )

    return HistoricalTailRisk(
        confidence=confidence,
        holding_period=holding_period,
        observations=count,
        tail_observations=tail_count,
        value_at_risk=float(value_at_risk),
        conditional_value_at_risk=float(conditional_value_at_risk),
        first_window_start=prices.points[0].trade_date,
        last_window_end=prices.points[-1].trade_date,
    )
