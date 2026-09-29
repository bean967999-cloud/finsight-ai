from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finsight.domain.claim_evidence import (
    ClaimContext,
    ClaimEvidenceLink,
    ClaimReview,
    ClaimReviewStatus,
    DocumentEvidencePointer,
    EvidenceRelation,
    NarrativeClaim,
    NumericCheckStatus,
    NumericClaim,
    QueryEvidencePointer,
    RiskEvidencePointer,
)


def context() -> ClaimContext:
    return ClaimContext(
        entity_code="TEST",
        metric_code="revenue",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        currency="CNY",
        consolidation_scope="consolidated",
    )


def claim() -> NumericClaim:
    return NumericClaim(
        claim_id="CL1",
        statement="2024 年合并营业收入为 100 亿元",
        context=context(),
        value=Decimal(100),
        unit="亿元",
    )


def document_pointer() -> DocumentEvidencePointer:
    return DocumentEvidencePointer(
        citation_id="C1",
        document_id=3,
        chunk_id=7,
        chunk_version=1,
        content_sha256="a" * 64,
        quoted_text_sha256="b" * 64,
        page_start=2,
        page_end=2,
    )


def query_pointer() -> QueryEvidencePointer:
    return QueryEvidencePointer(
        query_sha256="c" * 64,
        sql_sha256="d" * 64,
        row_index=0,
        row_sha256="e" * 64,
    )


def test_three_evidence_pointer_types_can_review_one_numeric_claim() -> None:
    links = tuple(
        ClaimEvidenceLink(pointer=pointer, relation="supports", reason="口径与数值一致")
        for pointer in (
            document_pointer(),
            query_pointer(),
            RiskEvidencePointer(
                subject_key="TEST",
                calculation_code="revenue_growth",
                input_sha256="f" * 64,
                report_sha256="1" * 64,
            ),
        )
    )
    review = ClaimReview(
        claim=claim(), links=links, status="verified", numeric_check_status="passed",
        assessment_reason="三类证据一致",
    )

    assert review.claim.value == Decimal(100)
    assert [link.pointer.kind for link in review.links] == ["document", "query", "risk"]
    assert review.status == ClaimReviewStatus.VERIFIED
    assert review.numeric_check_status == NumericCheckStatus.PASSED


def test_context_and_value_reject_ambiguous_or_invalid_numbers() -> None:
    with pytest.raises(ValidationError, match="period_start"):
        ClaimContext.model_validate(context().model_dump() | {
            "period_start": date(2025, 1, 1),
        })
    with pytest.raises(ValidationError, match="finite number"):
        NumericClaim.model_validate(claim().model_dump() | {"value": Decimal("NaN")})
    with pytest.raises(ValidationError, match="unit"):
        NumericClaim.model_validate(claim().model_dump() | {"unit": ""})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        NarrativeClaim(
            claim_id="CL2", statement="经营情况改善", context=context(), value=Decimal(100)
        )


def test_pointers_reject_broken_location_or_digest() -> None:
    with pytest.raises(ValidationError, match="page_start"):
        DocumentEvidencePointer.model_validate(document_pointer().model_dump() | {
            "page_start": 3,
        })
    with pytest.raises(ValidationError, match="row_sha256"):
        QueryEvidencePointer.model_validate(query_pointer().model_dump() | {
            "row_sha256": "not-a-hash",
        })


def test_verified_claim_requires_support_and_review_reason() -> None:
    with pytest.raises(ValidationError, match="supporting evidence"):
        ClaimReview(claim=claim(), status="verified", assessment_reason="看起来正确")
    with pytest.raises(ValidationError, match="assessment reason"):
        ClaimReview(
            claim=claim(), links=(ClaimEvidenceLink(
                pointer=document_pointer(), relation="supports", reason="引用一致"
            ),), status="verified",
        )
    with pytest.raises(ValidationError, match="reviewed relation requires a reason"):
        ClaimEvidenceLink(pointer=document_pointer(), relation="supports")
    with pytest.raises(ValidationError, match="passed numeric check"):
        ClaimReview(
            claim=claim(), links=(ClaimEvidenceLink(
                pointer=document_pointer(), relation="supports", reason="原文一致"
            ),), status="verified", assessment_reason="只有引用",
        )


def test_conflict_requires_both_sides_and_duplicate_pointer_is_rejected() -> None:
    supporting = ClaimEvidenceLink(
        pointer=document_pointer(), relation=EvidenceRelation.SUPPORTS, reason="原文支持"
    )
    contradicting = ClaimEvidenceLink(
        pointer=query_pointer(), relation=EvidenceRelation.CONTRADICTS, reason="数据库数值不同"
    )
    conflict = ClaimReview(
        claim=claim(), links=(supporting, contradicting), status="conflicted",
        assessment_reason="来源冲突",
    )
    assert conflict.status == ClaimReviewStatus.CONFLICTED
    with pytest.raises(ValidationError, match="supporting and contradicting"):
        ClaimReview(
            claim=claim(), links=(contradicting,), status="conflicted",
            assessment_reason="仅有反证",
        )
    with pytest.raises(ValidationError, match="unique"):
        ClaimReview(claim=claim(), links=(supporting, supporting))


def test_numeric_mismatch_status_cannot_be_used_for_narrative_claim() -> None:
    narrative = NarrativeClaim(claim_id="CL2", statement="收入增长", context=context())
    with pytest.raises(ValidationError, match="cannot have a numeric check result"):
        ClaimReview(
            claim=narrative, status="numeric_mismatch", numeric_check_status="failed",
            assessment_reason="计算有误",
        )
    with pytest.raises(ValidationError, match="failed numeric check"):
        ClaimReview(claim=claim(), status="numeric_mismatch", assessment_reason="计算有误")


@pytest.mark.parametrize("numeric_status", ["passed", "failed"])
def test_narrative_claim_cannot_have_numeric_result_even_when_verified(
    numeric_status: str,
) -> None:
    narrative = NarrativeClaim(claim_id="CL2", statement="经营情况改善", context=context())
    supporting = ClaimEvidenceLink(
        pointer=document_pointer(), relation="supports", reason="报告原文支持"
    )

    with pytest.raises(ValidationError, match="cannot have a numeric check result"):
        ClaimReview(
            claim=narrative, links=(supporting,), status="verified",
            numeric_check_status=numeric_status, assessment_reason="证据支持",
        )

    valid = ClaimReview(
        claim=narrative, links=(supporting,), status="verified",
        numeric_check_status="not_applicable", assessment_reason="证据支持",
    )
    assert valid.status == ClaimReviewStatus.VERIFIED
