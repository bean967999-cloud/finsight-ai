from datetime import date
from decimal import Decimal

import pytest

from finsight.domain.claim_evidence import (
    ClaimContext,
    NarrativeClaim,
    NumericClaim,
    QueryEvidencePointer,
)
from finsight.domain.evidence_fusion import EvidenceUsability
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.services.evidence_fusion import EvidenceFusionError, fuse_evidence


def claim() -> NumericClaim:
    return NumericClaim(
        claim_id="CL1",
        statement="2024 年合并收入为 100 元",
        context=ClaimContext(
            entity_code="TEST",
            metric_code="revenue",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            currency="CNY",
            consolidation_scope="consolidated",
        ),
        value=Decimal(100),
        unit="yuan",
    )


def fact(
    index: int,
    value: Decimal | None = Decimal(100),
    *,
    unit: str | None = "yuan",
    complete: bool = True,
    context: ClaimContext | None = None,
) -> NormalizedEvidence:
    dimensions = (
        EvidenceDimension.ENTITY,
        EvidenceDimension.METRIC,
        EvidenceDimension.PERIOD,
        EvidenceDimension.CURRENCY,
        EvidenceDimension.CONSOLIDATION_SCOPE,
        EvidenceDimension.UNIT,
    )
    return NormalizedEvidence(
        pointer=QueryEvidencePointer(
            query_sha256="a" * 64,
            sql_sha256="b" * 64,
            row_index=index,
            row_sha256=f"{index:064x}",
        ),
        context=context or claim().context,
        source_text=f"source {index}",
        value=value,
        unit=unit,
        grounded_dimensions=dimensions if complete else (EvidenceDimension.ENTITY,),
    )


def test_same_grounded_unit_detects_agreement_and_disagreement() -> None:
    result = fuse_evidence(claim(), (fact(1), fact(2), fact(3, Decimal(120))))
    assert result.agreement_count == 1
    assert len(result.disagreements) == 2
    assert result.incomparable_pair_count == 0
    assert all(item.usability == EvidenceUsability.COMPARABLE for item in result.assessments)
    assert result.disagreements[0].left.row_index == 1
    assert result.disagreements[0].right.row_index == 3


def test_missing_accounting_basis_is_not_a_conflict() -> None:
    result = fuse_evidence(claim(), (fact(1), fact(2, Decimal(120), complete=False)))
    assert result.disagreements == ()
    assert result.incomparable_pair_count == 1
    assert EvidenceDimension.CONSOLIDATION_SCOPE in result.assessments[1].missing_dimensions
    assert result.assessments[1].usability == EvidenceUsability.INCOMPLETE


def test_different_units_need_conversion_before_comparison() -> None:
    result = fuse_evidence(claim(), (fact(1), fact(2, Decimal(1), unit="hundred_yuan")))
    assert result.disagreements == ()
    assert result.incomparable_pair_count == 1


def test_different_context_is_incompatible() -> None:
    other = claim().context.model_copy(update={"currency": "USD"})
    result = fuse_evidence(claim(), (fact(1), fact(2, context=other)))
    assert result.assessments[1].usability == EvidenceUsability.INCOMPATIBLE
    assert result.disagreements == ()


def test_text_evidence_does_not_acquire_numeric_support() -> None:
    text = fact(1, None, unit=None, complete=False)
    result = fuse_evidence(claim(), (text, fact(2, Decimal(120))))
    assert result.assessments[0].usability == EvidenceUsability.INCOMPLETE
    assert result.disagreements == ()
    assert result.agreement_count == 0


def test_narrative_claim_is_not_semantically_verified_by_fusion() -> None:
    numeric = claim()
    narrative = NarrativeClaim(
        claim_id="CL2",
        statement="经营情况改善",
        context=numeric.context,
    )
    result = fuse_evidence(narrative, (fact(1), fact(2, Decimal(120))))
    assert all(item.usability == EvidenceUsability.INCOMPLETE for item in result.assessments)
    assert result.disagreements == ()
    assert result.agreement_count == 0


def test_duplicate_source_pointer_is_rejected() -> None:
    source = fact(1)
    with pytest.raises(EvidenceFusionError, match="unique"):
        fuse_evidence(claim(), (source, source))
