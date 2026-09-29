"""Versioned endpoint for explainable, provisional claim review."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.claim_evidence import Claim
from finsight.domain.evidence_review import EvidenceReviewPreview
from finsight.domain.normalized_evidence import NormalizedEvidence
from finsight.services.evidence_review import build_review_preview

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence-review"])


class EvidenceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: Claim
    evidence: tuple[NormalizedEvidence, ...] = Field(default=(), max_length=50)
    absolute_tolerance: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)


@router.post("/review-preview", response_model=EvidenceReviewPreview)
def review_evidence(payload: EvidenceReviewRequest) -> EvidenceReviewPreview:
    try:
        return build_review_preview(
            payload.claim,
            payload.evidence,
            absolute_tolerance=payload.absolute_tolerance,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
