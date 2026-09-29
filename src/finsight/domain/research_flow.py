"""Validated contracts for the multi-tool financial research workflow."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.grounded_document_answer import GroundedDocumentAnswer
from finsight.domain.normalized_evidence import NormalizedEvidence


class ResearchIntent(StrEnum):
    DOCUMENT = "document_research"
    STRUCTURED = "structured_query"
    RISK = "risk_analysis"
    MIXED = "mixed_research"
    UNSUPPORTED = "unsupported"


class ResearchTool(StrEnum):
    DOCUMENT_SEARCH = "document_search"
    STRUCTURED_QUERY = "structured_query"
    RISK_CALCULATION = "risk_calculation"


class ToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REFUSED = "refused"


class ResearchQuestion(BaseModel):
    """Boundary input; a price sequence is optional, never silently assumed."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=2000)
    prices: tuple[float, ...] | None = Field(default=None, min_length=3, max_length=10000)

    @model_validator(mode="after")
    def validate_prices(self) -> ResearchQuestion:
        if self.prices is not None and any(not math.isfinite(x) or x <= 0 for x in self.prices):
            raise ValueError("prices must be finite positive values")
        return self


class ResearchPlanItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    tool: ResearchTool
    reason: str = Field(min_length=1, max_length=300)


class ResearchToolResult(BaseModel):
    """A tool's outcome is separate from any claims derived from its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: ResearchTool
    status: ToolStatus
    evidence: tuple[NormalizedEvidence, ...] = ()
    document_answer: GroundedDocumentAnswer | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_outcome(self) -> ResearchToolResult:
        if self.document_answer is not None and (
            self.tool != ResearchTool.DOCUMENT_SEARCH or self.status != ToolStatus.SUCCEEDED
        ):
            raise ValueError("document answer requires successful document search")
        if self.status == ToolStatus.SUCCEEDED and self.error_code is not None:
            raise ValueError("successful tool result cannot contain an error code")
        if self.status != ToolStatus.SUCCEEDED and self.error_code is None:
            raise ValueError("unsuccessful tool result requires an error code")
        if self.status != ToolStatus.SUCCEEDED and self.evidence:
            raise ValueError("unsuccessful tool result cannot claim verified evidence")
        return self


class ToolOutputSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: ResearchTool
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=0)


class ResearchAnswer(BaseModel):
    """An explicit non-answer is preferable to an unsupported financial conclusion."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    status: AnswerStatus
    text: str = Field(min_length=1, max_length=10000)
    evidence: tuple[NormalizedEvidence, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_answer(self) -> ResearchAnswer:
        if self.status != AnswerStatus.ANSWERED and self.evidence:
            raise ValueError("non-answer must not present supporting evidence")
        if self.status != AnswerStatus.ANSWERED and not self.limitations:
            raise ValueError("non-answer requires an explicit limitation")
        return self
