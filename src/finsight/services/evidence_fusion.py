"""Find comparable evidence and cross-source disagreement without final verification."""

from __future__ import annotations

from itertools import combinations

from finsight.domain.claim_evidence import Claim, NumericClaim
from finsight.domain.evidence_fusion import (
    EvidenceAssessment,
    EvidenceDisagreement,
    EvidenceFusionResult,
    EvidenceUsability,
)
from finsight.domain.normalized_evidence import EvidenceDimension, NormalizedEvidence


class EvidenceFusionError(ValueError):
    """The submitted collection cannot be safely fused."""


def _required_dimensions(claim: Claim) -> tuple[EvidenceDimension, ...]:
    required = [EvidenceDimension.ENTITY, EvidenceDimension.METRIC, EvidenceDimension.PERIOD]
    if claim.context.currency is not None:
        required.append(EvidenceDimension.CURRENCY)
    if claim.context.consolidation_scope is not None:
        required.append(EvidenceDimension.CONSOLIDATION_SCOPE)
    if claim.context.adjustment_type is not None:
        required.append(EvidenceDimension.ADJUSTMENT_TYPE)
    if isinstance(claim, NumericClaim):
        required.append(EvidenceDimension.UNIT)
    return tuple(required)


def _assess(claim: Claim, evidence: NormalizedEvidence) -> EvidenceAssessment:
    if evidence.context != claim.context:
        return EvidenceAssessment(
            pointer=evidence.pointer,
            usability=EvidenceUsability.INCOMPATIBLE,
            reason="source context differs from the claim; financial bases cannot be mixed",
        )
    missing = tuple(
        dimension
        for dimension in _required_dimensions(claim)
        if dimension not in evidence.grounded_dimensions
    )
    if missing:
        return EvidenceAssessment(
            pointer=evidence.pointer,
            usability=EvidenceUsability.INCOMPLETE,
            missing_dimensions=missing,
            reason="source has not grounded every required financial dimension",
        )
    if not isinstance(claim, NumericClaim):
        return EvidenceAssessment(
            pointer=evidence.pointer,
            usability=EvidenceUsability.INCOMPLETE,
            reason="narrative meaning has not been assessed from source text",
        )
    if isinstance(claim, NumericClaim) and evidence.value is None:
        return EvidenceAssessment(
            pointer=evidence.pointer,
            usability=EvidenceUsability.INCOMPLETE,
            reason="numeric claim needs an extracted source value",
        )
    return EvidenceAssessment(
        pointer=evidence.pointer,
        usability=EvidenceUsability.COMPARABLE,
        reason="required context is grounded; final value verification is still pending",
    )


def fuse_evidence(claim: Claim, evidence: tuple[NormalizedEvidence, ...]) -> EvidenceFusionResult:
    """Compare exact same-unit facts only; leave conversion and claim verdict to later steps."""
    if len(evidence) > 50:
        raise EvidenceFusionError("a claim may have at most 50 evidence entries")
    pointers = [item.pointer.model_dump_json() for item in evidence]
    if len(pointers) != len(set(pointers)):
        raise EvidenceFusionError("evidence pointers must be unique")

    assessments = tuple(_assess(claim, item) for item in evidence)
    disagreements: list[EvidenceDisagreement] = []
    agreements = 0
    incomparable = 0
    if isinstance(claim, NumericClaim):
        for (left, left_assessment), (right, right_assessment) in combinations(
            zip(evidence, assessments, strict=True), 2
        ):
            if (
                left_assessment.usability != EvidenceUsability.COMPARABLE
                or right_assessment.usability != EvidenceUsability.COMPARABLE
                or left.unit != right.unit
            ):
                incomparable += 1
            elif left.value == right.value:
                agreements += 1
            else:
                disagreements.append(
                    EvidenceDisagreement(
                        left=left.pointer,
                        right=right.pointer,
                        reason="same grounded context and unit, but source values differ",
                    )
                )
    return EvidenceFusionResult(
        claim=claim,
        assessments=assessments,
        disagreements=tuple(disagreements),
        agreement_count=agreements,
        incomparable_pair_count=incomparable,
    )
