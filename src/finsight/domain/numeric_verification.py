"""Auditable outcomes for comparing a numeric claim with source facts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.claim_evidence import EvidencePointer, NumericClaim


class SourceNumericStatus(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INSUFFICIENT = "insufficient"


class NumericVerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    CONFLICTED = "conflicted"
    INSUFFICIENT = "insufficient"


class RecalculationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INSUFFICIENT = "insufficient"


class RiskRecalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pointer: EvidencePointer
    status: RecalculationStatus
    reported_value: Decimal
    recalculated_value: Decimal | None = None
    absolute_tolerance: Decimal
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_result(self) -> RiskRecalculationResult:
        if not self.absolute_tolerance.is_finite() or self.absolute_tolerance < 0:
            raise ValueError("absolute_tolerance must be finite and nonnegative")
        if self.status == RecalculationStatus.INSUFFICIENT and self.recalculated_value is not None:
            raise ValueError("insufficient recalculation cannot have a value")
        if self.status != RecalculationStatus.INSUFFICIENT and self.recalculated_value is None:
            raise ValueError("completed recalculation requires a value")
        return self


class SourceNumericCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pointer: EvidencePointer
    status: SourceNumericStatus
    source_value: Decimal | None = None
    source_unit: str | None = None
    converted_value: Decimal | None = None
    difference: Decimal | None = None
    reason: str = Field(min_length=1, max_length=500)


class NumericVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: NumericClaim
    status: NumericVerificationStatus
    absolute_tolerance: Decimal
    checks: tuple[SourceNumericCheck, ...]

    @model_validator(mode="after")
    def validate_tolerance(self) -> NumericVerificationResult:
        if not self.absolute_tolerance.is_finite() or self.absolute_tolerance < 0:
            raise ValueError("absolute_tolerance must be finite and nonnegative")
        return self
