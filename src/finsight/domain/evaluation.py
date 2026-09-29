"""Versioned golden-question and retrieval-evaluation contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.document_data import DocumentType
from finsight.domain.evidence import CitationStatus


class GoldenFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_code: str | None = Field(default=None, min_length=1, max_length=32)
    document_type: DocumentType | None = None
    report_year: int | None = Field(default=None, ge=1900, le=2100)


class EvidenceExpectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    contains_all: tuple[str, ...] = Field(min_length=1)
    page_number: int | None = Field(default=None, gt=0)
    document_title_contains: str | None = Field(default=None, min_length=1)


class GoldenQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    question_id: str = Field(pattern=r"^GQ-[0-9]{3}$")
    query: str = Field(min_length=2, max_length=2000)
    filters: GoldenFilter = GoldenFilter()
    expected_evidence: tuple[EvidenceExpectation, ...] = ()
    should_refuse: bool = False
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_answerability(self) -> GoldenQuestion:
        if self.should_refuse == bool(self.expected_evidence):
            raise ValueError("answerable questions need evidence; refusal questions must not have it")
        return self


class GoldenQuestionSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    retrieval_k: int = Field(gt=0, le=100)
    rerank_n: int = Field(gt=0, le=100)
    questions: tuple[GoldenQuestion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset(self) -> GoldenQuestionSet:
        ids = [question.question_id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("golden question IDs must be unique")
        if self.rerank_n > self.retrieval_k:
            raise ValueError("rerank_n must not exceed retrieval_k")
        if not any(question.should_refuse for question in self.questions):
            raise ValueError("golden set must include at least one refusal question")
        if not any(not question.should_refuse for question in self.questions):
            raise ValueError("golden set must include at least one answerable question")
        return self

    @classmethod
    def load(cls, path: Path) -> GoldenQuestionSet:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class ObservedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    document_title: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pages(self) -> ObservedEvidence:
        if self.page_end < self.page_start:
            raise ValueError("page_end must not be before page_start")
        return self


class EvaluationObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str = Field(pattern=r"^GQ-[0-9]{3}$")
    retrieved: tuple[ObservedEvidence, ...] = ()
    reranked: tuple[ObservedEvidence, ...] = ()
    citation_status: CitationStatus | None = None
    cited_evidence: ObservedEvidence | None = None
    quoted_text: str | None = Field(default=None, min_length=1)
    refused: bool = False
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_citation_target(self) -> EvaluationObservation:
        if (self.citation_status is None) != (self.cited_evidence is None):
            raise ValueError("citation status and cited evidence must be supplied together")
        if self.cited_evidence is not None and self.cited_evidence not in self.reranked:
            raise ValueError("cited evidence must be present in reranked results")
        if self.refused and self.cited_evidence is not None:
            raise ValueError("refusal cannot cite supporting evidence")
        if self.quoted_text is not None and (
            self.cited_evidence is None or self.quoted_text not in self.cited_evidence.content
        ):
            raise ValueError("quoted text must be anchored in cited evidence")
        return self


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    should_refuse: bool
    retrieval_rank: int | None
    rerank_rank: int | None
    citation_correct: bool
    refused: bool
    passed: bool
    failure_reasons: tuple[str, ...]


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_name: str
    dataset_version: str
    suite_name: str | None = None
    suite_version: str | None = None
    status: Literal["not_run", "observations_scored"]
    metrics: EvaluationMetrics | None = None
    cases: tuple[EvaluationCaseResult, ...] = ()
    unrun_question_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_run_status(self) -> RetrievalEvaluationReport:
        if self.status == "not_run" and (self.metrics is not None or self.cases):
            raise ValueError("not-run report cannot contain scores")
        if self.status == "observations_scored" and (
            self.metrics is None or self.unrun_question_ids
        ):
            raise ValueError("scored report needs metrics and no unrun questions")
        return self


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_name: str
    dataset_version: str
    question_count: int
    answerable_count: int
    refusal_count: int
    retrieval_recall_at_k: float
    rerank_hit_rate_at_n: float
    mean_reciprocal_rank: float
    citation_correctness: float
    refusal_accuracy: float
    unexpected_refusal_rate: float
    mean_latency_ms: float
