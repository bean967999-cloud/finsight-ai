from datetime import date, timedelta
from decimal import Decimal

import pytest

from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.historical_tail_risk import calculate_historical_tail_risk


def prices(*values: str) -> PriceSeries:
    start = date(2024, 1, 2)
    return PriceSeries(
        ticker="000001.SZ",
        adjustment_type="qfq",
        data_source="demo",
        data_version=1,
        points=tuple(
            PricePoint(start + timedelta(days=index), Decimal(value))
            for index, value in enumerate(values)
        ),
    )


def test_var_is_tail_cutoff_and_cvar_is_mean_of_worst_losses() -> None:
    # Five one-period returns: -20%, -10%, 0%, +10%, +20%.
    series = prices("100", "80", "72", "72", "79.2", "95.04")

    result = calculate_historical_tail_risk(
        series, confidence=0.6, minimum_observations=5
    )

    assert result.observations == 5
    assert result.tail_observations == 2
    assert result.value_at_risk == pytest.approx(0.10)
    assert result.conditional_value_at_risk == pytest.approx(0.15)
    assert result.first_window_start == date(2024, 1, 2)
    assert result.last_window_end == date(2024, 1, 7)


def test_holding_period_uses_actual_overlapping_price_windows() -> None:
    series = prices("100", "90", "81", "90", "100", "110")

    result = calculate_historical_tail_risk(
        series, confidence=0.6, holding_period=2, minimum_observations=3
    )

    # Four overlapping two-observation losses begin with 19%, 0%, then gains.
    assert result.observations == 4
    assert result.tail_observations == 2
    assert result.value_at_risk == 0
    assert result.conditional_value_at_risk == pytest.approx(0.095)
    assert result.holding_period == 2


def test_all_gains_produce_zero_positive_loss_measure() -> None:
    result = calculate_historical_tail_risk(
        prices("100", "110", "120", "130", "140", "150"),
        confidence=0.8,
        minimum_observations=5,
    )

    assert result.value_at_risk == 0
    assert result.conditional_value_at_risk == 0


def test_high_confidence_requires_enough_history_for_a_tail_observation() -> None:
    series = prices(*(str(100 + index) for index in range(21)))

    with pytest.raises(ValueError, match="at least 100 .* got 20"):
        calculate_historical_tail_risk(series, confidence=0.99)


def test_twenty_returns_at_95_percent_select_exactly_one_tail_loss() -> None:
    series = prices("100", "80", *("80" for _ in range(19)))

    result = calculate_historical_tail_risk(series, confidence=0.95)

    assert result.observations == 20
    assert result.tail_observations == 1
    assert result.value_at_risk == pytest.approx(0.2)
    assert result.conditional_value_at_risk == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"confidence": 1.0}, "confidence"),
        ({"confidence": 0.5}, "confidence"),
        ({"confidence": float("nan")}, "confidence"),
        ({"holding_period": 0}, "holding_period"),
        ({"holding_period": 253}, "holding_period"),
        ({"minimum_observations": 1}, "minimum_observations"),
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict[str, float | int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_historical_tail_risk(prices("100", "90"), **kwargs)
