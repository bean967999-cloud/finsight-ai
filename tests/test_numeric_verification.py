from datetime import date
from decimal import Decimal

import pytest

from finsight.domain.claim_evidence import ClaimContext, NumericClaim, QueryEvidencePointer
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.domain.numeric_verification import NumericVerificationStatus, SourceNumericStatus
from finsight.services.evidence_fusion import fuse_evidence
from finsight.services.numeric_verification import NumericVerificationError, verify_numeric_claim


def claim(
    value: Decimal = Decimal(1),
    unit: str = "亿元",
    *,
    currency: str | None = "CNY",
) -> NumericClaim:
    return NumericClaim(
        claim_id="CL1",
        statement="2024 年合并收入为 1 亿元",
        context=ClaimContext(
            entity_code="TEST",
            metric_code="revenue",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            currency=currency,
            consolidation_scope="consolidated",
        ),
        value=value,
        unit=unit,
    )


def fact(
    target: NumericClaim,
    index: int,
    value: Decimal,
    unit: str,
    *,
    full_period: bool = True,
    grounded_currency: bool = True,
) -> NormalizedEvidence:
    dimensions = [
        EvidenceDimension.ENTITY,
        EvidenceDimension.METRIC,
        EvidenceDimension.CONSOLIDATION_SCOPE,
        EvidenceDimension.UNIT,
    ]
    dimensions.append(EvidenceDimension.PERIOD if full_period else EvidenceDimension.PERIOD_END)
    if grounded_currency:
        dimensions.append(EvidenceDimension.CURRENCY)
    return NormalizedEvidence(
        pointer=QueryEvidencePointer(
            query_sha256="a" * 64,
            sql_sha256="b" * 64,
            row_index=index,
            row_sha256=f"{index:064x}",
        ),
        context=target.context,
        source_text=f"row {index}: {value} {unit}",
        value=value,
        unit=unit,
        grounded_dimensions=tuple(dimensions),
    )


def verify(
    target: NumericClaim,
    sources: tuple[NormalizedEvidence, ...],
    *,
    tolerance: Decimal = Decimal(0),
):
    return verify_numeric_claim(
        target,
        sources,
        fuse_evidence(target, sources),
        absolute_tolerance=tolerance,
    )


def test_yuan_to_hundred_million_yuan_is_exact() -> None:
    target = claim()
    result = verify(target, (fact(target, 1, Decimal(100_000_000), "yuan"),))
    assert result.status == NumericVerificationStatus.PASSED
    assert result.checks[0].converted_value == Decimal(1)
    assert result.checks[0].difference == 0


def test_same_source_value_does_not_override_wrong_claim() -> None:
    target = claim(Decimal(2))
    sources = (
        fact(target, 1, Decimal(100_000_000), "yuan"),
        fact(target, 2, Decimal(100_000_000), "yuan"),
    )
    assert fuse_evidence(target, sources).agreement_count == 1
    result = verify(target, sources)
    assert result.status == NumericVerificationStatus.FAILED
    assert all(check.status == SourceNumericStatus.CONTRADICTS for check in result.checks)


def test_support_and_contradiction_remain_visible() -> None:
    target = claim()
    result = verify(
        target,
        (
            fact(target, 1, Decimal(100_000_000), "yuan"),
            fact(target, 2, Decimal(200_000_000), "yuan"),
        ),
    )
    assert result.status == NumericVerificationStatus.CONFLICTED
    assert {check.status for check in result.checks} == {
        SourceNumericStatus.SUPPORTS,
        SourceNumericStatus.CONTRADICTS,
    }


def test_period_end_alone_cannot_verify_full_year() -> None:
    target = claim()
    result = verify(target, (fact(target, 1, Decimal(100_000_000), "yuan", full_period=False),))
    assert result.status == NumericVerificationStatus.INSUFFICIENT
    assert result.checks[0].converted_value is None


def test_money_cannot_pass_without_grounded_currency() -> None:
    target = claim(currency=None)
    result = verify(
        target, (fact(target, 1, Decimal(100_000_000), "yuan", grounded_currency=False),)
    )
    assert result.status == NumericVerificationStatus.INSUFFICIENT
    usd = claim(currency="USD")
    assert verify(usd, (fact(usd, 1, Decimal(100_000_000), "yuan"),)).status == (
        NumericVerificationStatus.INSUFFICIENT
    )


def test_percentage_and_fraction_convert_but_percentage_points_do_not() -> None:
    target = claim(Decimal("0.125"), "fraction", currency=None)
    supported = verify(target, (fact(target, 1, Decimal("12.5"), "%"),))
    assert supported.status == NumericVerificationStatus.PASSED
    assert supported.checks[0].converted_value == Decimal("0.125")
    unsupported = verify(target, (fact(target, 1, Decimal("12.5"), "个百分点"),))
    assert unsupported.status == NumericVerificationStatus.INSUFFICIENT


def test_explicit_tolerance_is_required_for_rounding_difference() -> None:
    target = claim(Decimal("0.2"), "fraction", currency=None)
    source = (fact(target, 1, Decimal("0.20000000001"), "fraction"),)
    assert verify(target, source).status == NumericVerificationStatus.FAILED
    assert verify(target, source, tolerance=Decimal("0.00000000002")).status == (
        NumericVerificationStatus.PASSED
    )
    with pytest.raises(NumericVerificationError, match="tolerance"):
        verify(target, source, tolerance=Decimal("-0.1"))


def test_fusion_and_source_pointer_must_match() -> None:
    target = claim()
    source = fact(target, 1, Decimal(100_000_000), "yuan")
    wrong_source = fact(target, 2, Decimal(100_000_000), "yuan")
    with pytest.raises(NumericVerificationError, match="pointers"):
        verify_numeric_claim(target, (wrong_source,), fuse_evidence(target, (source,)))
