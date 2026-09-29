from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from finsight.domain.claim_evidence import ClaimContext
from finsight.domain.numeric_verification import RecalculationStatus
from finsight.domain.return_series import PricePoint, PriceSeries
from finsight.services.evidence_normalization import from_asset_risk, from_portfolio_risk
from finsight.services.portfolio_risk import PortfolioPosition
from finsight.services.risk_analysis import RiskAnalysisService
from finsight.services.risk_recalculation import (
    RiskRecalculationError,
    verify_asset_risk_calculation,
    verify_portfolio_risk_calculation,
)


def prices(ticker: str, shift: int = 0) -> PriceSeries:
    return PriceSeries(
        ticker=ticker,
        adjustment_type="forward",
        data_source="fixture",
        data_version=1,
        points=tuple(
            PricePoint(
                date(2024, 1, 1) + timedelta(days=index),
                Decimal(100 + index + (index % 3) * (2 + shift)),
            )
            for index in range(26)
        ),
    )


def context(ticker: str, metric: str, start: date, end: date) -> ClaimContext:
    return ClaimContext(
        entity_code=ticker,
        metric_code=metric,
        period_start=start,
        period_end=end,
        adjustment_type="forward",
    )


def test_asset_report_recalculates_and_detects_tampering() -> None:
    source = prices("TEST")
    report = RiskAnalysisService().analyze_asset(source)
    basis = context("TEST", "max_drawdown", report.start_date, report.end_date)
    evidence = from_asset_risk(report, source, metric_code="max_drawdown", context=basis)
    result = verify_asset_risk_calculation(evidence, report, source)
    assert result.status == RecalculationStatus.PASSED
    altered = replace(
        report, drawdown=replace(report.drawdown, max_drawdown=report.drawdown.max_drawdown - 0.1)
    )
    altered_evidence = from_asset_risk(altered, source, metric_code="max_drawdown", context=basis)
    failed = verify_asset_risk_calculation(altered_evidence, altered, source)
    assert failed.status == RecalculationStatus.FAILED


def test_beta_needs_supplied_benchmark_for_recalculation() -> None:
    source = prices("TEST")
    benchmark = prices("INDEX", 1)
    report = RiskAnalysisService().analyze_asset(source, benchmark=benchmark)
    evidence = from_asset_risk(
        report,
        source,
        metric_code="beta",
        context=context("TEST", "beta", report.start_date, report.end_date),
    )
    assert verify_asset_risk_calculation(evidence, report, source).status == (
        RecalculationStatus.INSUFFICIENT
    )
    assert (
        verify_asset_risk_calculation(evidence, report, source, benchmark=benchmark).status
        == RecalculationStatus.PASSED
    )
    with pytest.raises(RiskRecalculationError, match="benchmark ticker"):
        verify_asset_risk_calculation(evidence, report, source, benchmark=prices("OTHER", 1))


def test_portfolio_report_recalculates_with_original_weights() -> None:
    positions = (PortfolioPosition(prices("AAA"), 0.6), PortfolioPosition(prices("BBB", 1), 0.4))
    report = RiskAnalysisService().analyze_portfolio(positions)
    first, last = report.portfolio.returns[0], report.portfolio.returns[-1]
    basis = context("portfolio-1", "annualized_volatility", first.period_start, last.period_end)
    evidence = from_portfolio_risk(
        report,
        positions,
        metric_code="annualized_volatility",
        context=basis,
    )
    assert verify_portfolio_risk_calculation(evidence, report, positions).status == (
        RecalculationStatus.PASSED
    )
    altered = replace(
        report,
        portfolio=replace(
            report.portfolio, annualized_volatility=report.portfolio.annualized_volatility + 0.1
        ),
    )
    altered_evidence = from_portfolio_risk(
        altered,
        positions,
        metric_code="annualized_volatility",
        context=basis,
    )
    assert verify_portfolio_risk_calculation(altered_evidence, altered, positions).status == (
        RecalculationStatus.FAILED
    )
    wrong_positions = (
        PortfolioPosition(prices("AAA"), 0.7),
        PortfolioPosition(prices("BBB", 1), 0.3),
    )
    with pytest.raises(ValueError, match="provenance"):
        verify_portfolio_risk_calculation(evidence, report, wrong_positions)
    with pytest.raises(RiskRecalculationError, match="tolerance"):
        verify_portfolio_risk_calculation(
            evidence,
            report,
            positions,
            absolute_tolerance=Decimal(-1),
        )
