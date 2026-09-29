"""Persistable server-produced extractive answer with explicitly anchored citations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.evidence import Citation


class GenerationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["local", "generated", "fallback"]
    reason: Literal[
        "disabled", "key_missing", "scope_not_authorized", "public_query_not_approved",
        "public_source_not_approved", "export_boundary_rejected", "provider_unavailable",
        "provider_failed", "model_refused", "claim_changed", "verified_evidence_selection",
    ]
    attempts: int = Field(default=0, ge=0, le=2)


class GroundedDocumentAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=10000)
    citations: tuple[Citation, ...] = Field(min_length=1)
    generation: GenerationReport | None = None
