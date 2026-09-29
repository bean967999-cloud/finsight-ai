"""Pre-verification comparison of normalized evidence sources."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.claim_evidence import Claim, EvidencePointer
from finsight.domain.normalized_evidence import EvidenceDimension


class EvidenceUsability(StrEnum):
    COMPARABLE = "comparable"
    INCOMPLETE = "incomplete"
    INCOMPATIBLE = "incompatible"


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pointer: EvidencePointer
    usability: EvidenceUsability
    missing_dimensions: tuple[EvidenceDimension, ...] = ()
    reason: str = Field(min_length=1, max_length=500)


class EvidenceDisagreement(BaseModel):
    """Two eligible sources disagree; neither is declared correct yet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    left: EvidencePointer
    right: EvidencePointer
    reason: str = Field(min_length=1, max_length=500)


class EvidenceFusionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    assessments: tuple[EvidenceAssessment, ...]
    disagreements: tuple[EvidenceDisagreement, ...] = ()
    agreement_count: int = Field(ge=0)
    incomparable_pair_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> EvidenceFusionResult:
        count = len(self.assessments)
        if (self.agreement_count + self.incomparable_pair_count + len(self.disagreements)) > (
            count * (count - 1) // 2
        ):
            raise ValueError("pair counts exceed available evidence pairs")
        return self
