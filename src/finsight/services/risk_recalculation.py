"""Recalculate selected risk values from the submitted dated price inputs."""

from __future__ import annotations

from decimal import Decimal

from finsight.domain.normalized_evidence import NormalizedEvidence
from finsight.domain.numeric_verification import RecalculationStatus, RiskRecalculationResult
from finsight.domain.return_series import PriceSeries
from finsight.services.evidence_normalization import from_asset_risk, from_portfolio_risk
from finsight.services.portfolio_risk import PortfolioPosition
from finsight.services.risk_analysis import (
    AssetRiskReport,
    PortfolioRiskReport,
    RiskAnalysisService,
)


class RiskRecalculationError(ValueError):
    """The supplied report, input, and evidence do not refer to the same calculation."""


def _check_source(original: NormalizedEvidence, reconstructed: NormalizedEvidence) -> None:
    if original.pointer != reconstructed.pointer or original.value != reconstructed.value:
        raise RiskRecalculationError("risk evidence does not match report and input digests")


def _result(
    original: NormalizedEvidence,
    recalculated: Decimal | None,
    *,
    absolute_tolerance: Decimal,
) -> RiskRecalculationResult:
    if not absolute_tolerance.is_finite() or absolute_tolerance < 0:
        raise RiskRecalculationError("absolute_tolerance must be finite and nonnegative")
    if original.value is None:
        raise RiskRecalculationError("risk evidence needs a numeric value")
    if recalculated is None:
        return RiskRecalculationResult(
            pointer=original.pointer,
            status=RecalculationStatus.INSUFFICIENT,
            reported_value=original.value,
            absolute_tolerance=absolute_tolerance,
            reason="benchmark price series is required to recalculate beta",
        )
    passed = abs(original.value - recalculated) <= absolute_tolerance
    return RiskRecalculationResult(
        pointer=original.pointer,
        status=RecalculationStatus.PASSED if passed else RecalculationStatus.FAILED,
        reported_value=original.value,
        recalculated_value=recalculated,
        absolute_tolerance=absolute_tolerance,
        reason="report value matches recomputation"
        if passed
        else "report value differs from recomputation",
    )


def verify_asset_risk_calculation(
    evidence: NormalizedEvidence,
    report: AssetRiskReport,
    prices: PriceSeries,
    *,
    benchmark: PriceSeries | None = None,
    absolute_tolerance: Decimal = Decimal("1e-12"),
) -> RiskRecalculationResult:
    if evidence.pointer.kind != "risk":
        raise RiskRecalculationError("asset calculation needs risk evidence")
    metric = evidence.pointer.calculation_code
    source = from_asset_risk(report, prices, metric_code=metric, context=evidence.context)
    _check_source(evidence, source)
    if metric == "beta" and benchmark is None:
        return _result(evidence, None, absolute_tolerance=absolute_tolerance)
    if (
        metric == "beta"
        and report.beta is not None
        and benchmark is not None
        and benchmark.ticker != report.beta.benchmark_ticker
    ):
        raise RiskRecalculationError("benchmark ticker differs from risk report")
    recomputed = RiskAnalysisService().analyze_asset(
        prices,
        benchmark=benchmark,
        confidence=report.tail_risk.confidence,
        holding_period=report.tail_risk.holding_period,
        minimum_observations=2,
        annual_risk_free_rate=report.sharpe.annual_risk_free_rate,
        trading_days_per_year=report.volatility.trading_days_per_year,
    )
    recalculated = from_asset_risk(
        recomputed,
        prices,
        metric_code=metric,
        context=evidence.context,
    ).value
    return _result(evidence, recalculated, absolute_tolerance=absolute_tolerance)


def verify_portfolio_risk_calculation(
    evidence: NormalizedEvidence,
    report: PortfolioRiskReport,
    positions: tuple[PortfolioPosition, ...],
    *,
    absolute_tolerance: Decimal = Decimal("1e-12"),
) -> RiskRecalculationResult:
    if evidence.pointer.kind != "risk":
        raise RiskRecalculationError("portfolio calculation needs risk evidence")
    metric = evidence.pointer.calculation_code
    source = from_portfolio_risk(report, positions, metric_code=metric, context=evidence.context)
    _check_source(evidence, source)
    recomputed = RiskAnalysisService().analyze_portfolio(
        positions,
        trading_days_per_year=report.portfolio.trading_days_per_year,
    )
    recalculated = from_portfolio_risk(
        recomputed,
        positions,
        metric_code=metric,
        context=evidence.context,
    ).value
    return _result(evidence, recalculated, absolute_tolerance=absolute_tolerance)
