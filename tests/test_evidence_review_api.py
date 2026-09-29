from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from finsight.domain.claim_evidence import (
    ClaimContext,
    NarrativeClaim,
    NumericClaim,
    QueryEvidencePointer,
    RiskEvidencePointer,
)
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence
from finsight.main import app
from finsight.services.evidence_review import build_review_preview


def claim() -> NumericClaim:
    return NumericClaim(
        claim_id="CL1",
        statement="2024 年合并收入为 1 亿元",
        context=ClaimContext(
            entity_code="TEST",
            metric_code="revenue",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            currency="CNY",
            consolidation_scope="consolidated",
        ),
        value=Decimal(1),
        unit="亿元",
    )


def fact(index: int, amount: int) -> NormalizedEvidence:
    return NormalizedEvidence(
        pointer=QueryEvidencePointer(
            query_sha256="a" * 64,
            sql_sha256="b" * 64,
            row_index=index,
            row_sha256=f"{index:064x}",
        ),
        context=claim().context,
        source_text=f"revenue={amount} yuan",
        value=Decimal(amount),
        unit="yuan",
        grounded_dimensions=(
            EvidenceDimension.ENTITY,
            EvidenceDimension.METRIC,
            EvidenceDimension.PERIOD,
            EvidenceDimension.CURRENCY,
            EvidenceDimension.CONSOLIDATION_SCOPE,
            EvidenceDimension.UNIT,
        ),
    )


def payload(*evidence: NormalizedEvidence) -> dict[str, object]:
    return {
        "claim": claim().model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }


def test_preview_explains_conversion_but_never_certifies_caller_sources() -> None:
    response = TestClient(app).post(
        "/api/v1/evidence/review-preview",
        json=payload(fact(1, 100_000_000)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "caller_supplied_unverified"
    assert body["review"]["status"] == "pending"
    assert body["review"]["links"][0]["relation"] == "pending"
    assert body["numeric_verification"]["status"] == "passed"
    assert Decimal(body["numeric_verification"]["checks"][0]["converted_value"]) == 1
    assert body["fusion"]["assessments"][0]["usability"] == "comparable"
    assert "caller" in body["limitations"][0]


def test_preview_keeps_source_conflict_and_claim_check_separate() -> None:
    response = TestClient(app).post(
        "/api/v1/evidence/review-preview",
        json=payload(fact(1, 100_000_000), fact(2, 200_000_000)),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["fusion"]["disagreements"]) == 1
    assert body["numeric_verification"]["status"] == "conflicted"
    assert [item["status"] for item in body["numeric_verification"]["checks"]] == [
        "supports",
        "contradicts",
    ]
    assert body["review"]["status"] == "pending"


def test_duplicate_pointer_and_invalid_tolerance_are_rejected() -> None:
    client = TestClient(app)
    source = fact(1, 100_000_000)
    duplicated = client.post("/api/v1/evidence/review-preview", json=payload(source, source))
    assert duplicated.status_code == 422
    assert "unique" in duplicated.json()["detail"]
    invalid = client.post(
        "/api/v1/evidence/review-preview",
        json=payload(source)
        | {
            "absolute_tolerance": "-1",
        },
    )
    assert invalid.status_code == 422


def test_narrative_preview_stays_pending_without_semantic_review() -> None:
    narrative = NarrativeClaim(
        claim_id="CL2",
        statement="经营情况改善",
        context=claim().context,
    )
    preview = build_review_preview(narrative, (fact(1, 100_000_000),))
    assert preview.numeric_verification is None
    assert preview.review.status == "pending"
    assert any("semantically" in item for item in preview.limitations)


def test_no_evidence_is_explicitly_incomplete() -> None:
    preview = build_review_preview(claim(), ())
    assert preview.numeric_verification is not None
    assert preview.numeric_verification.status == "insufficient"
    assert "No evidence was supplied." in preview.limitations


def test_risk_source_warns_that_api_did_not_recalculate_it() -> None:
    source = fact(1, 100_000_000)
    risk = source.model_copy(
        update={
            "pointer": RiskEvidencePointer(
                subject_key="TEST",
                calculation_code="revenue",
                input_sha256="a" * 64,
                report_sha256="b" * 64,
            ),
        }
    )
    preview = build_review_preview(claim(), (risk,))
    assert any("not recomputed" in item for item in preview.limitations)
    assert preview.review.status == "pending"


def test_narrative_preview_rejects_invalid_tolerance_too() -> None:
    narrative = NarrativeClaim(
        claim_id="CL2",
        statement="经营情况改善",
        context=claim().context,
    )
    with pytest.raises(ValueError, match="tolerance"):
        build_review_preview(narrative, (), absolute_tolerance=Decimal(-1))
