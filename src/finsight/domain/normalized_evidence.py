"""One evidence shape with explicit provenance and grounded dimensions."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.claim_evidence import ClaimContext, EvidencePointer


class EvidenceDimension(StrEnum):
    ENTITY = "entity"
    METRIC = "metric"
    PERIOD = "period"
    PERIOD_END = "period_end"
    UNIT = "unit"
    CURRENCY = "currency"
    CONSOLIDATION_SCOPE = "consolidation_scope"
    ADJUSTMENT_TYPE = "adjustment_type"


class NormalizedEvidence(BaseModel):
    """Extracted source fact, before support/conflict and numeric verification."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    pointer: EvidencePointer
    context: ClaimContext
    source_text: str = Field(min_length=1, max_length=4000)
    value: Decimal | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    grounded_dimensions: tuple[EvidenceDimension, ...] = ()

    @model_validator(mode="after")
    def validate_fact(self) -> NormalizedEvidence:
        if (self.value is None) != (self.unit is None):
            raise ValueError("numeric evidence requires both value and unit")
        if len(self.grounded_dimensions) != len(set(self.grounded_dimensions)):
            raise ValueError("grounded dimensions must be unique")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("numeric evidence value must be finite")
        return self
