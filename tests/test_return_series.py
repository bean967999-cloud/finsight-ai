from datetime import date
from decimal import Decimal
from math import isclose, log

import pytest

from finsight.domain.return_series import (
    PricePoint,
    PriceSeries,
    ReturnMethod,
    calculate_returns,
)


def prices(*points: tuple[int, str]) -> PriceSeries:
    return PriceSeries(
        ticker="000001.SZ",
        adjustment_type="qfq",
        data_source="demo",
        data_version=1,
        points=tuple(PricePoint(date(2024, 1, day), Decimal(value)) for day, value in points),
    )


def test_simple_and_log_returns_keep_dates_and_provenance() -> None:
    series = prices((2, "100"), (3, "110"), (5, "99"))

    simple = calculate_returns(series)
    logarithmic = calculate_returns(series, ReturnMethod.LOG)

    assert [point.trade_date.day for point in simple.points] == [3, 5]
    assert [point.value for point in simple.points] == pytest.approx([0.1, -0.1])
    assert isclose(logarithmic.points[0].value, log(1.1))
    assert isclose(logarithmic.points[1].value, log(0.9))
    assert simple.adjustment_type == "qfq"
    assert simple.data_source == "demo"
    assert simple.method is ReturnMethod.SIMPLE


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (((3, "100"), (2, "110")), "strictly increasing"),
        (((2, "100"), (2, "110")), "strictly increasing"),
        (((2, "100"), (3, "0")), "finite and positive"),
        (((2, "100"), (3, "NaN")), "finite and positive"),
        (((2, "100"), (3, "Infinity")), "finite and positive"),
        (((2, "100"),), "at least 2"),
    ],
)
def test_invalid_price_series_is_rejected(
    entries: tuple[tuple[int, str], ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        prices(*entries)


def test_invalid_metadata_and_unrepresentable_ratio_are_rejected() -> None:
    with pytest.raises(ValueError, match="data_source"):
        PriceSeries("000001.SZ", "none", "", 1, prices((2, "1"), (3, "2")).points)
    with pytest.raises(ValueError, match="price ratio"):
        calculate_returns(prices((2, "1E-1000"), (3, "1E+1000")))
