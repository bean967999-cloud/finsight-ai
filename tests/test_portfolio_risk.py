from datetime import date
from decimal import Decimal
from math import sqrt

import pytest

from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.portfolio_risk import PortfolioPosition, calculate_portfolio_risk


def prices(ticker: str, *entries: tuple[int, str], adjustment: str = "qfq") -> PriceSeries:
    return PriceSeries(
        ticker=ticker,
        adjustment_type=adjustment,
        data_source="demo",
        data_version=1,
        points=tuple(PricePoint(date(2024, 1, day), Decimal(value)) for day, value in entries),
    )


def test_identical_assets_have_unit_correlation_and_weighted_risk_contributions() -> None:
    first = prices("A", (2, "100"), (3, "110"), (4, "99"))
    second = prices("B", (2, "200"), (3, "220"), (4, "198"))

    result = calculate_portfolio_risk(
        (PortfolioPosition(first, 0.25), PortfolioPosition(second, 0.75)),
        trading_days_per_year=4,
    )

    assert result.aligned_observations == 2
    assert [point.value for point in result.returns] == pytest.approx([0.1, -0.1])
    for row in result.covariance_matrix:
        assert row == pytest.approx((0.02, 0.02))
    assert result.correlation_matrix == ((1.0, 1.0), (1.0, 1.0))
    assert result.daily_volatility == pytest.approx(sqrt(0.02))
    assert result.annualized_volatility == pytest.approx(sqrt(0.02) * 2)
    assert [item.share_of_portfolio_volatility for item in result.risk_contributions] == (
        pytest.approx([0.25, 0.75])
    )
    assert sum(
        item.annualized_volatility_contribution for item in result.risk_contributions
    ) == pytest.approx(result.annualized_volatility)


def test_opposite_returns_can_cancel_portfolio_volatility() -> None:
    first = prices("A", (2, "100"), (3, "110"), (4, "99"))
    second = prices("B", (2, "100"), (3, "90"), (4, "99"))

    result = calculate_portfolio_risk(
        (PortfolioPosition(first, 0.5), PortfolioPosition(second, 0.5))
    )

    assert result.correlation_matrix[0][1] == pytest.approx(-1)
    assert result.daily_volatility == 0
    assert all(item.share_of_portfolio_volatility is None for item in result.risk_contributions)


def test_hedging_asset_can_have_negative_risk_contribution() -> None:
    first = prices("A", (2, "100"), (3, "110"), (4, "99"))
    second = prices("B", (2, "100"), (3, "90"), (4, "99"))

    result = calculate_portfolio_risk(
        (PortfolioPosition(first, 0.75), PortfolioPosition(second, 0.25))
    )

    assert [item.share_of_portfolio_volatility for item in result.risk_contributions] == (
        pytest.approx([1.5, -0.5])
    )
    assert sum(
        item.annualized_volatility_contribution for item in result.risk_contributions
    ) == pytest.approx(result.annualized_volatility)


def test_one_asset_portfolio_matches_its_own_volatility() -> None:
    series = prices("A", (2, "100"), (3, "110"), (4, "99"))
    result = calculate_portfolio_risk((PortfolioPosition(series, 1.0),))

    assert result.tickers == ("A",)
    assert result.correlation_matrix == ((1.0,),)
    assert result.risk_contributions[0].share_of_portfolio_volatility == pytest.approx(1)
    assert result.risk_contributions[0].annualized_volatility_contribution == pytest.approx(
        result.annualized_volatility
    )


def test_constant_asset_has_undefined_correlation() -> None:
    varying = prices("A", (2, "100"), (3, "110"), (4, "99"))
    constant = prices("B", (2, "100"), (3, "100"), (4, "100"))

    result = calculate_portfolio_risk(
        (PortfolioPosition(varying, 0.5), PortfolioPosition(constant, 0.5))
    )

    assert result.correlation_matrix[0][1] is None
    assert result.correlation_matrix[1][1] is None
    assert result.risk_contributions[1].share_of_portfolio_volatility == 0


def test_mismatched_interval_is_excluded_even_if_end_date_matches() -> None:
    first = prices("A", (2, "100"), (4, "110"), (5, "120"))
    second = prices("B", (3, "100"), (4, "110"), (5, "120"))

    with pytest.raises(ValueError, match="shared return windows"):
        calculate_portfolio_risk(
            (PortfolioPosition(first, 0.5), PortfolioPosition(second, 0.5))
        )


@pytest.mark.parametrize("weights", [(0.6, 0.3), (1.1, -0.1), (float("nan"), 0.5)])
def test_invalid_weights_are_rejected(weights: tuple[float, float]) -> None:
    first = prices("A", (2, "100"), (3, "110"), (4, "99"))
    second = prices("B", (2, "100"), (3, "110"), (4, "99"))

    with pytest.raises(ValueError, match="weights"):
        calculate_portfolio_risk(
            (PortfolioPosition(first, weights[0]), PortfolioPosition(second, weights[1]))
        )


def test_duplicate_ticker_and_mixed_adjustments_are_rejected() -> None:
    first = prices("A", (2, "100"), (3, "110"), (4, "99"))
    second = prices("B", (2, "100"), (3, "110"), (4, "99"), adjustment="none")

    with pytest.raises(ValueError, match="unique"):
        calculate_portfolio_risk((PortfolioPosition(first, 0.5), PortfolioPosition(first, 0.5)))
    with pytest.raises(ValueError, match="adjustment"):
        calculate_portfolio_risk((PortfolioPosition(first, 0.5), PortfolioPosition(second, 0.5)))
