"""Convert document, query, and risk outputs into traceable facts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from finsight.domain.claim_evidence import (
    ClaimContext,
    DocumentEvidencePointer,
    QueryEvidencePointer,
    RiskEvidencePointer,
)
from finsight.domain.evidence import Citation, CitationStatus
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.domain.query_execution import QueryExecutionResult
from finsight.domain.query_plan import StructuredQueryPlan
from finsight.domain.return_series import PriceSeries
from finsight.services.portfolio_risk import PortfolioPosition
from finsight.services.risk_analysis import AssetRiskReport, PortfolioRiskReport


class EvidenceNormalizationError(ValueError):
    """The selected source cannot establish the requested evidence fact."""


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def from_citation(citation: Citation, context: ClaimContext) -> NormalizedEvidence:
    if citation.status != CitationStatus.VERIFIED:
        raise EvidenceNormalizationError("document citation must be verified")
    candidate = citation.evidence.candidate
    if candidate.company_code is None or candidate.company_code != context.entity_code:
        raise EvidenceNormalizationError("document company does not match claim context")
    return NormalizedEvidence(
        pointer=DocumentEvidencePointer(
            citation_id=citation.citation_id,
            document_id=candidate.document_id,
            chunk_id=candidate.chunk_id,
            chunk_version=candidate.chunk_version,
            content_sha256=candidate.content_sha256,
            quoted_text_sha256=sha256(citation.quoted_text.encode("utf-8")).hexdigest(),
            page_start=candidate.page_start,
            page_end=candidate.page_end,
        ),
        context=context,
        source_text=citation.quoted_text,
        grounded_dimensions=(EvidenceDimension.ENTITY,),
    )


def _numeric_value(raw: Any) -> Decimal:
    if raw is None or isinstance(raw, bool):
        raise EvidenceNormalizationError("source value must be numeric and present")
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise EvidenceNormalizationError("source value must be numeric and present") from exc
    if not value.is_finite():
        raise EvidenceNormalizationError("source value must be finite")
    return value


def from_query_row(
    execution: QueryExecutionResult,
    plan: StructuredQueryPlan,
    *,
    row_index: int,
    value_field: str,
    context: ClaimContext,
) -> NormalizedEvidence:
    if execution.query_sha256 != plan.query_sha256:
        raise EvidenceNormalizationError("query plan and result digests differ")
    if execution.row_count != len(execution.rows):
        raise EvidenceNormalizationError("query result row count is inconsistent")
    if not 0 <= row_index < execution.row_count:
        raise EvidenceNormalizationError("query row index is out of range")
    row = execution.rows[row_index]
    if tuple(row) != execution.columns:
        raise EvidenceNormalizationError("query row columns differ from result contract")
    if value_field not in row:
        raise EvidenceNormalizationError("requested value field is absent from query row")
    if context.entity_code not in {row.get("company_code"), row.get("ticker")}:
        raise EvidenceNormalizationError("query entity does not match claim context")
    row_metric = row.get("item_code", row.get("indicator_code"))
    if row_metric is not None and row_metric != context.metric_code:
        raise EvidenceNormalizationError("query metric does not match claim context")
    if row_metric is None and not (
        value_field == context.metric_code or value_field.endswith(f"_{context.metric_code}")
    ):
        raise EvidenceNormalizationError("query value field does not match claim metric")

    grounded = [EvidenceDimension.ENTITY, EvidenceDimension.METRIC]
    if plan.time.start_date is not None:
        if (context.period_start, context.period_end) != (
            plan.time.start_date,
            plan.time.end_date,
        ):
            raise EvidenceNormalizationError("query date range does not match claim context")
        grounded.append(EvidenceDimension.PERIOD)
    else:
        report_date = row.get("report_date")
        if not isinstance(report_date, date) or report_date != context.period_end:
            raise EvidenceNormalizationError("query report date does not match claim context")
        if report_date.year not in plan.time.report_years:
            raise EvidenceNormalizationError("query report year is absent from plan")
        grounded.append(EvidenceDimension.PERIOD_END)
        if (
            row.get("period_type") == "annual"
            and context.period_start == date(report_date.year, 1, 1)
            and report_date == date(report_date.year, 12, 31)
        ):
            grounded.append(EvidenceDimension.PERIOD)

    row_currency = row.get("currency")
    if context.currency is not None and row_currency is not None:
        if row_currency != context.currency:
            raise EvidenceNormalizationError("query currency does not match claim context")
        grounded.append(EvidenceDimension.CURRENCY)
    row_scope = row.get("consolidation_scope")
    if context.consolidation_scope is not None and row_scope is not None:
        if row_scope != context.consolidation_scope:
            raise EvidenceNormalizationError("query scope does not match claim context")
        grounded.append(EvidenceDimension.CONSOLIDATION_SCOPE)

    unit = row.get("unit") or row_currency
    if not isinstance(unit, str) or not unit:
        raise EvidenceNormalizationError("query row does not provide a numeric unit")
    grounded.append(EvidenceDimension.UNIT)
    value = _numeric_value(row[value_field])
    return NormalizedEvidence(
        pointer=QueryEvidencePointer(
            query_sha256=execution.query_sha256,
            sql_sha256=execution.sql_sha256,
            row_index=row_index,
            row_sha256=_digest(row),
        ),
        context=context,
        source_text=f"{value_field}={value} {unit}",
        value=value,
        unit=unit,
        grounded_dimensions=tuple(grounded),
    )


_ASSET_VALUES = {
    "annualized_volatility": lambda report: report.volatility.annualized_volatility,
    "max_drawdown": lambda report: report.drawdown.max_drawdown,
    "historical_var": lambda report: report.tail_risk.value_at_risk,
    "historical_cvar": lambda report: report.tail_risk.conditional_value_at_risk,
    "sharpe_ratio": lambda report: report.sharpe.sharpe_ratio,
    "beta": lambda report: report.beta.beta if report.beta is not None else None,
}
_PORTFOLIO_VALUES = {
    "annualized_volatility": lambda report: report.portfolio.annualized_volatility,
    "annualized_mean_return": lambda report: report.portfolio.annualized_mean_return,
}


def from_asset_risk(
    report: AssetRiskReport,
    prices: PriceSeries,
    *,
    metric_code: str,
    context: ClaimContext,
) -> NormalizedEvidence:
    if metric_code not in _ASSET_VALUES:
        raise EvidenceNormalizationError("unsupported asset risk metric")
    if (report.ticker, report.adjustment_type, report.data_source, report.data_version) != (
        prices.ticker,
        prices.adjustment_type,
        prices.data_source,
        prices.data_version,
    ):
        raise EvidenceNormalizationError("risk report and price input provenance differ")
    if (
        report.price_observations != len(prices.points)
        or report.start_date != prices.points[0].trade_date
        or report.end_date != prices.points[-1].trade_date
    ):
        raise EvidenceNormalizationError("risk report and price input period differ")
    if (
        context.entity_code != report.ticker
        or context.metric_code != metric_code
        or (context.period_start, context.period_end) != (report.start_date, report.end_date)
        or context.adjustment_type != report.adjustment_type
    ):
        raise EvidenceNormalizationError("risk report does not match claim context")
    raw = _ASSET_VALUES[metric_code](report)
    if raw is None:
        raise EvidenceNormalizationError("requested risk metric is undefined")
    value = _numeric_value(raw)
    unit = "dimensionless" if metric_code in {"sharpe_ratio", "beta"} else "fraction"
    return NormalizedEvidence(
        pointer=RiskEvidencePointer(
            subject_key=report.ticker,
            calculation_code=metric_code,
            input_sha256=_digest(asdict(prices)),
            report_sha256=_digest(asdict(report)),
        ),
        context=context,
        source_text=f"{metric_code}={value} {unit}",
        value=value,
        unit=unit,
        grounded_dimensions=(
            EvidenceDimension.ENTITY,
            EvidenceDimension.METRIC,
            EvidenceDimension.PERIOD,
            EvidenceDimension.UNIT,
            EvidenceDimension.ADJUSTMENT_TYPE,
        ),
    )


def from_portfolio_risk(
    report: PortfolioRiskReport,
    positions: tuple[PortfolioPosition, ...],
    *,
    metric_code: str,
    context: ClaimContext,
) -> NormalizedEvidence:
    if metric_code not in _PORTFOLIO_VALUES:
        raise EvidenceNormalizationError("unsupported portfolio risk metric")
    if not report.portfolio.returns:
        raise EvidenceNormalizationError("portfolio report has no return periods")
    if (
        report.portfolio.tickers != tuple(position.prices.ticker for position in positions)
        or report.portfolio.weights != tuple(position.weight for position in positions)
        or report.sources
        != tuple(
            (position.prices.ticker, position.prices.data_source, position.prices.data_version)
            for position in positions
        )
    ):
        raise EvidenceNormalizationError("portfolio report and input provenance differ")
    period = (
        report.portfolio.returns[0].period_start,
        report.portfolio.returns[-1].period_end,
    )
    if (
        context.metric_code != metric_code
        or (context.period_start, context.period_end) != period
        or context.adjustment_type != report.portfolio.adjustment_type
    ):
        raise EvidenceNormalizationError("portfolio report does not match claim context")
    value = _numeric_value(_PORTFOLIO_VALUES[metric_code](report))
    return NormalizedEvidence(
        pointer=RiskEvidencePointer(
            subject_key=context.entity_code,
            calculation_code=metric_code,
            input_sha256=_digest(tuple(asdict(position) for position in positions)),
            report_sha256=_digest(asdict(report)),
        ),
        context=context,
        source_text=f"{metric_code}={value} fraction",
        value=value,
        unit="fraction",
        grounded_dimensions=(
            EvidenceDimension.METRIC,
            EvidenceDimension.PERIOD,
            EvidenceDimension.UNIT,
            EvidenceDimension.ADJUSTMENT_TYPE,
        ),
    )
