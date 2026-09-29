"""Contracts separating retrieval candidates, reranking, and citations."""

from enum import StrEnum
from hashlib import sha256
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.document_chunking import ChunkKind, SourceBlockRef
from finsight.domain.document_data import DocumentType


class CitationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class EvidenceCandidate(BaseModel):
    """One authoritative PostgreSQL chunk selected by first-stage retrieval."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    vector_id: str = Field(min_length=1, max_length=100)
    document_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    parse_job_id: int = Field(gt=0)
    chunk_version: int = Field(gt=0)
    kind: ChunkKind
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    section_path: tuple[str, ...] = ()
    source_blocks: tuple[SourceBlockRef, ...] = Field(min_length=1)
    document_title: str = Field(min_length=1, max_length=500)
    document_type: DocumentType
    company_code: str | None = Field(default=None, max_length=32)
    report_year: int | None = Field(default=None, ge=1900, le=2100)
    source_url: str | None = Field(default=None, max_length=2000)
    retrieval_rank: int = Field(gt=0)
    retrieval_score: float

    @model_validator(mode="after")
    def validate_candidate(self) -> "EvidenceCandidate":
        if not isfinite(self.retrieval_score):
            raise ValueError("retrieval_score must be finite")
        if sha256(self.content.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("candidate content does not match content_sha256")
        coordinates = [(ref.page_number, ref.block_index) for ref in self.source_blocks]
        if coordinates != sorted(set(coordinates)):
            raise ValueError("source_blocks must be unique and in reading order")
        if self.page_start != coordinates[0][0] or self.page_end != coordinates[-1][0]:
            raise ValueError("page range must match source_blocks")
        if any(not title for title in self.section_path):
            raise ValueError("section_path must not contain empty titles")
        return self


class RerankedEvidence(BaseModel):
    """A candidate with an independent relevance score and final rank."""

    model_config = ConfigDict(frozen=True)

    candidate: EvidenceCandidate
    reranker_name: str = Field(min_length=1, max_length=100)
    reranker_version: str = Field(min_length=1, max_length=100)
    rerank_score: float
    final_rank: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_rerank_score(self) -> "RerankedEvidence":
        if not isfinite(self.rerank_score):
            raise ValueError("rerank_score must be finite")
        return self


class Citation(BaseModel):
    """A source reference whose text and provenance can be independently verified."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    citation_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    evidence: RerankedEvidence
    quoted_text: str = Field(min_length=1)
    status: CitationStatus = CitationStatus.PENDING
    verification_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_status_and_quote(self) -> "Citation":
        content = self.evidence.candidate.content
        if self.quoted_text not in content:
            raise ValueError("quoted_text must be an exact substring of candidate content")
        if self.status == CitationStatus.PENDING and self.verification_reason is not None:
            raise ValueError("pending citation must not have a verification reason")
        if self.status != CitationStatus.PENDING and self.verification_reason is None:
            raise ValueError("verified or rejected citation requires a reason")
        return self


class EvidenceBundle(BaseModel):
    """Ordered evidence prepared for a later response or evidence endpoint."""

    model_config = ConfigDict(frozen=True)

    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_count: int = Field(ge=0)
    citations: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def validate_bundle(self) -> "EvidenceBundle":
        ids = [citation.citation_id for citation in self.citations]
        ranks = [citation.evidence.final_rank for citation in self.citations]
        chunk_ids = [citation.evidence.candidate.chunk_id for citation in self.citations]
        if ids != [f"C{index}" for index in range(1, len(ids) + 1)]:
            raise ValueError("citation IDs must be contiguous and ordered")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("final ranks must be contiguous and ordered")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("one chunk must not appear more than once")
        if len(self.citations) > self.candidate_count:
            raise ValueError("citations cannot exceed candidate_count")
        return self
