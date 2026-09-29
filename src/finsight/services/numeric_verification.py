"""Verify a numeric claim against grounded source values and explicit unit rules."""

from __future__ import annotations

from decimal import Decimal

from finsight.domain.claim_evidence import NumericClaim
from finsight.domain.evidence_fusion import EvidenceFusionResult, EvidenceUsability
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.domain.numeric_verification import (
    NumericVerificationResult,
    NumericVerificationStatus,
    SourceNumericCheck,
    SourceNumericStatus,
)


class NumericVerificationError(ValueError):
    """Fusion result, evidence, or tolerance is not valid for this check."""


_UNITS: dict[str, tuple[str, Decimal]] = {
    "yuan": ("money", Decimal(1)),
    "元": ("money", Decimal(1)),
    "thousand_yuan": ("money", Decimal(1_000)),
    "ten_thousand_yuan": ("money", Decimal(10_000)),
    "万元": ("money", Decimal(10_000)),
    "hundred_million_yuan": ("money", Decimal(100_000_000)),
    "亿元": ("money", Decimal(100_000_000)),
    "万亿元": ("money", Decimal(1_000_000_000_000)),
    "fraction": ("proportion", Decimal(1)),
    "ratio": ("proportion", Decimal(1)),
    "%": ("proportion", Decimal("0.01")),
    "percent": ("proportion", Decimal("0.01")),
    "dimensionless": ("dimensionless", Decimal(1)),
    "percentage_point": ("percentage_point", Decimal(1)),
    "个百分点": ("percentage_point", Decimal(1)),
}


def _convert(
    value: Decimal,
    source_unit: str,
    target_unit: str,
    *,
    currency: str | None,
    currency_grounded: bool,
) -> Decimal | None:
    source = _UNITS.get(source_unit)
    target = _UNITS.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    if source[0] == "money" and (currency != "CNY" or not currency_grounded):
        return None
    return value * source[1] / target[1]


def verify_numeric_claim(
    claim: NumericClaim,
    evidence: tuple[NormalizedEvidence, ...],
    fusion: EvidenceFusionResult,
    *,
    absolute_tolerance: Decimal = Decimal(0),
) -> NumericVerificationResult:
    """Compare claim value only after source context and units have been checked."""
    if not absolute_tolerance.is_finite() or absolute_tolerance < 0:
        raise NumericVerificationError("absolute_tolerance must be finite and nonnegative")
    if fusion.claim != claim or len(fusion.assessments) != len(evidence):
        raise NumericVerificationError("fusion result does not match claim and evidence")
    if any(
        assessment.pointer != fact.pointer
        for assessment, fact in zip(fusion.assessments, evidence, strict=True)
    ):
        raise NumericVerificationError("fusion evidence order or pointers differ")

    checks: list[SourceNumericCheck] = []
    for fact, assessment in zip(evidence, fusion.assessments, strict=True):
        if assessment.usability != EvidenceUsability.COMPARABLE:
            checks.append(
                SourceNumericCheck(
                    pointer=fact.pointer,
                    status=SourceNumericStatus.INSUFFICIENT,
                    source_value=fact.value,
                    source_unit=fact.unit,
                    reason=f"source is {assessment.usability.value}: {assessment.reason}",
                )
            )
            continue
        if fact.value is None or fact.unit is None:
            raise NumericVerificationError("fusion marked a nonnumeric source comparable")
        converted = _convert(
            fact.value,
            fact.unit,
            claim.unit,
            currency=claim.context.currency,
            currency_grounded=EvidenceDimension.CURRENCY in fact.grounded_dimensions,
        )
        if converted is None:
            checks.append(
                SourceNumericCheck(
                    pointer=fact.pointer,
                    status=SourceNumericStatus.INSUFFICIENT,
                    source_value=fact.value,
                    source_unit=fact.unit,
                    reason="unit conversion is unsupported or monetary currency is ungrounded",
                )
            )
            continue
        difference = abs(converted - claim.value)
        supports = difference <= absolute_tolerance
        checks.append(
            SourceNumericCheck(
                pointer=fact.pointer,
                status=SourceNumericStatus.SUPPORTS
                if supports
                else SourceNumericStatus.CONTRADICTS,
                source_value=fact.value,
                source_unit=fact.unit,
                converted_value=converted,
                difference=difference,
                reason="converted value is within tolerance"
                if supports
                else "converted value differs from claim beyond tolerance",
            )
        )

    statuses = {check.status for check in checks}
    if SourceNumericStatus.SUPPORTS in statuses and SourceNumericStatus.CONTRADICTS in statuses:
        result_status = NumericVerificationStatus.CONFLICTED
    elif SourceNumericStatus.CONTRADICTS in statuses:
        result_status = NumericVerificationStatus.FAILED
    elif SourceNumericStatus.SUPPORTS in statuses:
        result_status = NumericVerificationStatus.PASSED
    else:
        result_status = NumericVerificationStatus.INSUFFICIENT
    return NumericVerificationResult(
        claim=claim,
        status=result_status,
        absolute_tolerance=absolute_tolerance,
        checks=tuple(checks),
    )
