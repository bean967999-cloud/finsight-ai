"""Assemble explainable evidence comparison without claiming source authenticity."""

from __future__ import annotations

from decimal import Decimal

from finsight.domain.claim_evidence import Claim, ClaimEvidenceLink, ClaimReview, NumericClaim
from finsight.domain.evidence_review import EvidenceReviewPreview
from finsight.domain.normalized_evidence import NormalizedEvidence
from finsight.services.evidence_fusion import fuse_evidence
from finsight.services.numeric_verification import verify_numeric_claim


def build_review_preview(
    claim: Claim,
    evidence: tuple[NormalizedEvidence, ...],
    *,
    absolute_tolerance: Decimal = Decimal(0),
) -> EvidenceReviewPreview:
    """Show comparison details; keep ClaimReview pending until sources are reread."""
    if not absolute_tolerance.is_finite() or absolute_tolerance < 0:
        raise ValueError("absolute_tolerance must be finite and nonnegative")
    fusion = fuse_evidence(claim, evidence)
    numeric = (
        verify_numeric_claim(claim, evidence, fusion, absolute_tolerance=absolute_tolerance)
        if isinstance(claim, NumericClaim)
        else None
    )
    limitations = [
        (
            "Evidence was submitted by the caller; original document, database row, and "
            "price input were not independently reloaded by this endpoint."
        )
    ]
    if not evidence:
        limitations.append("No evidence was supplied.")
    if any(item.pointer.kind == "risk" for item in evidence):
        limitations.append("Risk calculations were not recomputed by this endpoint.")
    if numeric is None:
        limitations.append("Narrative support has not been semantically reviewed.")
    return EvidenceReviewPreview(
        review=ClaimReview(
            claim=claim,
            links=tuple(ClaimEvidenceLink(pointer=item.pointer) for item in evidence),
        ),
        fusion=fusion,
        numeric_verification=numeric,
        limitations=tuple(limitations),
    )
