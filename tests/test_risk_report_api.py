from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from finsight.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_risk_client(agent_auth):
    client.headers.update(agent_auth.headers())
    yield
    client.headers.pop("Authorization", None)


def series(ticker: str, values: list[str]) -> dict[str, object]:
    start = date(2024, 1, 2)
    return {
        "ticker": ticker,
        "adjustment_type": "qfq",
        "data_source": "demo",
        "data_version": 1,
        "points": [
            {
                "trade_date": (start + timedelta(days=index)).isoformat(),
                "close_price": value,
            }
            for index, value in enumerate(values)
        ],
    }


def test_asset_report_returns_metrics_period_and_warnings() -> None:
    asset = series("ASSET", [str(100 + index) for index in range(21)])
    benchmark = series("INDEX", [str(200 + 2 * index) for index in range(21)])

    response = client.post(
        "/api/v1/risk/asset-report",
        json={"asset": asset, "benchmark": benchmark, "confidence": 0.95},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ASSET"
    assert body["data_source"] == "demo"
    assert body["price_observations"] == 21
    assert body["tail_risk"]["observations"] == 20
    assert body["tail_risk"]["tail_observations"] == 1
    assert body["volatility"]["return_observations"] == 20
    assert body["drawdown"]["max_drawdown"] == 0
    assert body["beta"]["aligned_observations"] == 20
    assert body["units"]["returns_and_volatility"] == "fraction"
    assert body["warnings"]


def test_asset_report_rejects_insufficient_tail_history() -> None:
    response = client.post(
        "/api/v1/risk/asset-report",
        json={"asset": series("ASSET", ["100", "110", "99"])},
    )

    assert response.status_code == 422
    assert "return observations" in response.json()["detail"]


def test_portfolio_report_exposes_matrix_and_source_lineage() -> None:
    first = series("A", ["100", "110", "99"])
    second = series("B", ["200", "220", "198"])
    response = client.post(
        "/api/v1/risk/portfolio-report",
        json={
            "positions": [
                {"prices": first, "weight": 0.25},
                {"prices": second, "weight": 0.75},
            ],
            "trading_days_per_year": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio"]["tickers"] == ["A", "B"]
    assert body["portfolio"]["aligned_observations"] == 2
    assert body["portfolio"]["correlation_matrix"][0][1] == 1
    assert body["sources"] == [["A", "demo", 1], ["B", "demo", 1]]
    assert body["units"]["covariance"] == "fraction_squared"
    assert body["warnings"]


def test_portfolio_report_rejects_invalid_weight_sum() -> None:
    response = client.post(
        "/api/v1/risk/portfolio-report",
        json={
            "positions": [
                {"prices": series("A", ["100", "110", "99"]), "weight": 0.4},
                {"prices": series("B", ["100", "110", "99"]), "weight": 0.4},
            ]
        },
    )

    assert response.status_code == 422
    assert "sum to 1" in response.json()["detail"]


def test_invalid_price_order_is_a_client_error() -> None:
    asset = series("ASSET", ["100", "110", "99"])
    assert isinstance(asset["points"], list)
    asset["points"][1]["trade_date"] = asset["points"][0]["trade_date"]

    response = client.post("/api/v1/risk/asset-report", json={"asset": asset})

    assert response.status_code == 422
    assert "strictly increasing" in response.json()["detail"]
