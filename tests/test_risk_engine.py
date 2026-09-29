from finsight.services.risk_engine import RiskEngine


def test_risk_engine_returns_expected_shape():
    prices = [100, 101, 99, 103, 102, 105, 104, 108]
    metrics = RiskEngine.analyze(prices)

    assert metrics.observations == len(prices)
    assert metrics.annualized_volatility >= 0
    assert metrics.max_drawdown <= 0
    assert metrics.historical_var >= 0
    assert metrics.historical_cvar >= metrics.historical_var


def test_risk_engine_rejects_non_positive_prices():
    try:
        RiskEngine.analyze([100, 0, 101])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "positive" in str(exc)
