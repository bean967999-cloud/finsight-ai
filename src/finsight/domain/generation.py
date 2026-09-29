"""Strict, bounded external generation contracts; no credentials or transport here."""

from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    enabled: bool = False
    provider: Literal["deepseek"] = "deepseek"
    endpoint: Literal["https://api.deepseek.com/chat/completions"] = (
        "https://api.deepseek.com/chat/completions"
    )
    max_attempts: int = Field(default=2, ge=1, le=2)
    max_daily_attempts: int = Field(default=20, ge=1, le=20)
    max_output_tokens: int = Field(default=512, ge=64, le=512)
    request_timeout_seconds: int = Field(default=20, ge=1, le=20)
    total_timeout_seconds: int = Field(default=45, ge=1, le=45)

    @model_validator(mode="after")
    def coherent_deadline(self):
        if self.total_timeout_seconds < self.request_timeout_seconds:
            raise ValueError("total deadline must cover one attempt")
        return self


class PublicEvidenceExcerpt(BaseModel):
    """Export DTO, deliberately excluding internal identity and storage fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    citation_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=200)
    report_year: int = Field(ge=1900, le=2100)
    page_number: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=1200)


class PublicGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=500)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[PublicEvidenceExcerpt, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def consistent_envelope(self):
        if self.query_sha256 != sha256(self.query.encode()).hexdigest():
            raise ValueError("query digest mismatch")
        ids = [item.citation_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence IDs")
        if len({item.report_year for item in self.evidence}) != 1:
            raise ValueError("cross-year generation requires a separate contract")
        return self


class GenerationStatus(StrEnum):
    ANSWERED = "answered"
    REFUSED = "refused"


class RefusalReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED_QUESTION = "unsupported_question"


class GeneratedQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    citation_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    quoted_text: str = Field(min_length=1, max_length=1200)


class GeneratedEvidenceAnswer(BaseModel):
    """Untrusted model output, not yet a verified financial answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: GenerationStatus
    quotes: tuple[GeneratedQuote, ...] = Field(default=(), max_length=3)
    refusal_reason: RefusalReason | None = None

    @model_validator(mode="after")
    def coherent_answer(self):
        if self.status == GenerationStatus.ANSWERED:
            if not self.quotes or self.refusal_reason is not None:
                raise ValueError("answered output needs evidence, not a refusal reason")
        elif self.quotes or self.refusal_reason is None:
            raise ValueError("refusal needs a reason and must not contain claims")
        ids = [item.citation_id for item in self.quotes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate answer references")
        return self
