from datetime import date
from decimal import Decimal
from math import sqrt

import pytest

from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.price_risk import calculate_drawdown, calculate_volatility


def prices(*values: str) -> PriceSeries:
    return PriceSeries(
        ticker="000001.SZ",
        adjustment_type="qfq",
        data_source="demo",
        data_version=1,
        points=tuple(
            PricePoint(date(2024, 1, index + 2), Decimal(value))
            for index, value in enumerate(values)
        ),
    )


def test_volatility_matches_hand_calculated_sample() -> None:
    # 100 -> 110 -> 99 gives returns +10% and -10%; sample std = sqrt(0.02).
    result = calculate_volatility(prices("100", "110", "99"), trading_days_per_year=4)

    assert result.return_observations == 2
    assert result.daily_volatility == pytest.approx(sqrt(0.02))
    assert result.annualized_volatility == pytest.approx(sqrt(0.02) * 2)


def test_drawdown_tracks_wealth_peak_and_trough() -> None:
    result = calculate_drawdown(prices("100", "120", "90", "110", "130"))

    assert [point.wealth_index for point in result.curve] == pytest.approx(
        [1.0, 1.2, 0.9, 1.1, 1.3]
    )
    assert [point.drawdown for point in result.curve] == pytest.approx(
        [0.0, 0.0, -0.25, 110 / 120 - 1, 0.0]
    )
    assert result.max_drawdown == pytest.approx(-0.25)
    assert result.peak_date == date(2024, 1, 3)
    assert result.trough_date == date(2024, 1, 4)


def test_no_drawdown_has_no_peak_or_trough() -> None:
    result = calculate_drawdown(prices("100", "110", "120"))

    assert result.max_drawdown == 0.0
    assert result.peak_date is None
    assert result.trough_date is None


def test_repeated_high_uses_first_peak_and_first_worst_trough() -> None:
    result = calculate_drawdown(prices("100", "120", "120", "90", "90"))

    assert result.max_drawdown == pytest.approx(-0.25)
    assert result.peak_date == date(2024, 1, 3)
    assert result.trough_date == date(2024, 1, 5)


def test_volatility_rejects_insufficient_prices_and_invalid_calendar() -> None:
    with pytest.raises(ValueError, match="at least 3 prices"):
        calculate_volatility(prices("100", "110"))
    with pytest.raises(ValueError, match="trading_days_per_year"):
        calculate_volatility(prices("100", "110", "99"), trading_days_per_year=0)
