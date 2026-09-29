"""Reviewable claims and pointers to document, query, and calculation evidence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimContext(BaseModel):
    """Dimensions that must agree before two numeric facts can be compared."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    entity_code: str = Field(min_length=1, max_length=64)
    metric_code: str = Field(min_length=1, max_length=100)
    period_start: date
    period_end: date
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    consolidation_scope: str | None = Field(default=None, min_length=1, max_length=32)
    adjustment_type: str | None = Field(default=None, min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_period(self) -> ClaimContext:
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


class NumericClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: Literal["numeric"] = "numeric"
    claim_id: str = Field(pattern=r"^CL[1-9][0-9]*$")
    statement: str = Field(min_length=1, max_length=2000)
    context: ClaimContext
    value: Decimal
    unit: str = Field(min_length=1, max_length=32)

class NarrativeClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: Literal["narrative"] = "narrative"
    claim_id: str = Field(pattern=r"^CL[1-9][0-9]*$")
    statement: str = Field(min_length=1, max_length=2000)
    context: ClaimContext


Claim = Annotated[NumericClaim | NarrativeClaim, Field(discriminator="kind")]
_HASH = r"^[0-9a-f]{64}$"


class DocumentEvidencePointer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["document"] = "document"
    citation_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    document_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    chunk_version: int = Field(gt=0)
    content_sha256: str = Field(pattern=_HASH)
    quoted_text_sha256: str = Field(pattern=_HASH)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_pages(self) -> DocumentEvidencePointer:
        if self.page_start > self.page_end:
            raise ValueError("page_start must not be after page_end")
        return self


class QueryEvidencePointer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["query"] = "query"
    query_sha256: str = Field(pattern=_HASH)
    sql_sha256: str = Field(pattern=_HASH)
    row_index: int = Field(ge=0)
    row_sha256: str = Field(pattern=_HASH)


class RiskEvidencePointer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: Literal["risk"] = "risk"
    subject_key: str = Field(min_length=1, max_length=100)
    calculation_code: str = Field(min_length=1, max_length=100)
    input_sha256: str = Field(pattern=_HASH)
    report_sha256: str = Field(pattern=_HASH)


EvidencePointer = Annotated[
    DocumentEvidencePointer | QueryEvidencePointer | RiskEvidencePointer,
    Field(discriminator="kind"),
]


class EvidenceRelation(StrEnum):
    PENDING = "pending"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class ClaimEvidenceLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pointer: EvidencePointer
    relation: EvidenceRelation = EvidenceRelation.PENDING
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_relation(self) -> ClaimEvidenceLink:
        if self.relation == EvidenceRelation.PENDING and self.reason is not None:
            raise ValueError("pending relation must not have a reason")
        if self.relation != EvidenceRelation.PENDING and self.reason is None:
            raise ValueError("reviewed relation requires a reason")
        return self


class ClaimReviewStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    NUMERIC_MISMATCH = "numeric_mismatch"
    INSUFFICIENT = "insufficient"


class NumericCheckStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class ClaimReview(BaseModel):
    """Claim with traceable links; final statuses must obey minimal evidence rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    links: tuple[ClaimEvidenceLink, ...] = Field(default=(), max_length=50)
    status: ClaimReviewStatus = ClaimReviewStatus.PENDING
    numeric_check_status: NumericCheckStatus = NumericCheckStatus.PENDING
    assessment_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_review(self) -> ClaimReview:
        pointers = [link.pointer for link in self.links]
        if len(pointers) != len({pointer.model_dump_json() for pointer in pointers}):
            raise ValueError("evidence pointers must be unique within a claim")
        if isinstance(self.claim, NarrativeClaim) and self.numeric_check_status in {
            NumericCheckStatus.PASSED,
            NumericCheckStatus.FAILED,
        }:
            raise ValueError("narrative claim cannot have a numeric check result")
        if self.status == ClaimReviewStatus.PENDING:
            if self.assessment_reason is not None:
                raise ValueError("pending review must not have an assessment reason")
            return self
        if self.assessment_reason is None:
            raise ValueError("completed review requires an assessment reason")
        relations = {link.relation for link in self.links}
        if self.status == ClaimReviewStatus.VERIFIED and relations != {EvidenceRelation.SUPPORTS}:
            raise ValueError("verified claim requires reviewed supporting evidence only")
        if (
            self.status == ClaimReviewStatus.VERIFIED
            and isinstance(self.claim, NumericClaim)
            and self.numeric_check_status != NumericCheckStatus.PASSED
        ):
            raise ValueError("verified numeric claim requires a passed numeric check")
        if self.status == ClaimReviewStatus.CONFLICTED and not {
            EvidenceRelation.SUPPORTS,
            EvidenceRelation.CONTRADICTS,
        }.issubset(relations):
            raise ValueError("conflicted claim requires supporting and contradicting evidence")
        if self.status == ClaimReviewStatus.NUMERIC_MISMATCH and not isinstance(
            self.claim, NumericClaim
        ):
            raise ValueError("numeric mismatch requires a numeric claim")
        if (
            self.status == ClaimReviewStatus.NUMERIC_MISMATCH
            and self.numeric_check_status != NumericCheckStatus.FAILED
        ):
            raise ValueError("numeric mismatch requires a failed numeric check")
        return self
