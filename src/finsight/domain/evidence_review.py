"""Explainable, non-authoritative review preview for submitted evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.claim_evidence import ClaimReview
from finsight.domain.evidence_fusion import EvidenceFusionResult
from finsight.domain.numeric_verification import NumericVerificationResult


class EvidenceReviewPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"
    review: ClaimReview
    fusion: EvidenceFusionResult
    numeric_verification: NumericVerificationResult | None = None
    limitations: tuple[str, ...] = Field(min_length=1)
