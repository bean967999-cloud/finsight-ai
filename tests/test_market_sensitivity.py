from datetime import date
from decimal import Decimal
from math import sqrt

import pytest

from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.market_sensitivity import calculate_beta, calculate_sharpe


def prices(ticker: str, *entries: tuple[int, str]) -> PriceSeries:
    return PriceSeries(
        ticker=ticker,
        adjustment_type="qfq",
        data_source="demo",
        data_version=1,
        points=tuple(PricePoint(date(2024, 1, day), Decimal(value)) for day, value in entries),
    )


def test_sharpe_uses_period_risk_free_rate_and_sample_volatility() -> None:
    series = prices("ASSET", (2, "100"), (3, "110"), (4, "99"))
    # Four trading periods per synthetic year; effective annual rate 21% -> 4.8795% per period.
    result = calculate_sharpe(
        series, annual_risk_free_rate=0.21, trading_days_per_year=4
    )

    daily_risk_free = 1.21 ** 0.25 - 1
    expected_daily_volatility = sqrt(0.02)
    assert result.observations == 2
    assert result.risk_free_rate_per_period == pytest.approx(daily_risk_free)
    assert result.annualized_mean_return == pytest.approx(0)
    assert result.annualized_volatility == pytest.approx(expected_daily_volatility * 2)
    assert result.sharpe_ratio == pytest.approx(
        -daily_risk_free / expected_daily_volatility * 2
    )


def test_zero_asset_volatility_has_undefined_sharpe() -> None:
    result = calculate_sharpe(
        prices("ASSET", (2, "100"), (3, "100"), (4, "100"))
    )

    assert result.annualized_volatility == 0
    assert result.sharpe_ratio is None


def test_beta_uses_matching_price_intervals() -> None:
    # Benchmark returns +10%, -10%; asset returns +20%, -20% -> beta 2.
    asset = prices("ASSET", (2, "100"), (3, "120"), (4, "96"))
    benchmark = prices("INDEX", (2, "100"), (3, "110"), (4, "99"))

    result = calculate_beta(asset, benchmark)

    assert result.beta == pytest.approx(2.0)
    assert result.aligned_observations == 2
    assert result.first_period_end == date(2024, 1, 3)
    assert result.last_period_end == date(2024, 1, 4)
    assert result.asset_ticker == "ASSET"
    assert result.benchmark_ticker == "INDEX"


def test_same_end_date_with_different_start_is_not_aligned() -> None:
    asset = prices("ASSET", (2, "100"), (4, "120"), (5, "130"))
    benchmark = prices("INDEX", (3, "100"), (4, "110"), (5, "120"))

    with pytest.raises(ValueError, match="matching return windows"):
        calculate_beta(asset, benchmark)


def test_constant_benchmark_has_undefined_beta() -> None:
    asset = prices("ASSET", (2, "100"), (3, "110"), (4, "99"))
    benchmark = prices("INDEX", (2, "100"), (3, "100"), (4, "100"))

    result = calculate_beta(asset, benchmark)

    assert result.aligned_observations == 2
    assert result.beta is None


@pytest.mark.parametrize("rate", [-1.0, float("nan"), float("inf")])
def test_invalid_risk_free_rate_is_rejected(rate: float) -> None:
    series = prices("ASSET", (2, "100"), (3, "110"), (4, "99"))
    with pytest.raises(ValueError, match="annual_risk_free_rate"):
        calculate_sharpe(series, annual_risk_free_rate=rate)


def test_sharpe_rejects_one_return_and_invalid_trading_days() -> None:
    with pytest.raises(ValueError, match="at least 3 prices"):
        calculate_sharpe(prices("ASSET", (2, "100"), (3, "110")))
    with pytest.raises(ValueError, match="trading_days_per_year"):
        calculate_sharpe(
            prices("ASSET", (2, "100"), (3, "110"), (4, "99")),
            trading_days_per_year=0,
        )
