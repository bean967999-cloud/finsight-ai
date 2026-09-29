from pathlib import Path

import pytest

from finsight.domain.evaluation import EvaluationObservation, GoldenQuestionSet, ObservedEvidence
from finsight.domain.evidence import CitationStatus
from finsight.services.evidence_evaluation import EvidenceEvaluator

DATASET = Path(__file__).parents[1] / "Evaluation" / "GoldenQuestionsV1.json"


def observed(content: str, page: int) -> ObservedEvidence:
    return ObservedEvidence(
        content=content, page_start=page, page_end=page,
        document_title="Public financial disclosure excerpt",
    )


def test_golden_questions_v1_is_versioned_and_has_refusal_case() -> None:
    dataset = GoldenQuestionSet.load(DATASET)
    assert dataset.version == "v1"
    assert dataset.retrieval_k == 20 and dataset.rerank_n == 5
    assert len(dataset.questions) == 4
    assert sum(question.should_refuse for question in dataset.questions) == 1


def test_metrics_separate_retrieval_rerank_citation_and_refusal() -> None:
    dataset = GoldenQuestionSet.load(DATASET)
    irrelevant = observed("unrelated content", 9)
    observations = (
        EvaluationObservation(
            question_id="GQ-001",
            retrieved=(irrelevant, observed("assets were 1,396,927", 2)),
            reranked=(observed("assets were 1,396,927", 2),),
            citation_status=CitationStatus.VERIFIED,
            cited_evidence=observed("assets were 1,396,927", 2), latency_ms=100,
        ),
        EvaluationObservation(
            question_id="GQ-002",
            retrieved=(irrelevant, observed("dividend per share was 6.80", 1)),
            reranked=(irrelevant, observed("dividend per share was 6.80", 1)),
            citation_status=CitationStatus.VERIFIED,
            cited_evidence=observed("dividend per share was 6.80", 1), latency_ms=200,
        ),
        EvaluationObservation(
            question_id="GQ-003",
            retrieved=(irrelevant, irrelevant, observed("increase was 26%", 1)),
            reranked=(irrelevant,), citation_status=CitationStatus.REJECTED,
            cited_evidence=irrelevant, latency_ms=300,
        ),
        EvaluationObservation(
            question_id="GQ-004", refused=True, latency_ms=400,
        ),
    )

    metrics = EvidenceEvaluator().evaluate(dataset, observations)

    assert metrics.retrieval_recall_at_k == 1.0
    assert metrics.rerank_hit_rate_at_n == pytest.approx(2 / 3)
    assert metrics.mean_reciprocal_rank == 0.5
    assert metrics.citation_correctness == pytest.approx(2 / 3)
    assert metrics.refusal_accuracy == 1.0
    assert metrics.unexpected_refusal_rate == 0.0
    assert metrics.mean_latency_ms == 250.0


def test_evaluation_rejects_incomplete_or_duplicate_runs() -> None:
    dataset = GoldenQuestionSet.load(DATASET)
    observation = EvaluationObservation(question_id="GQ-001", latency_ms=1)
    with pytest.raises(ValueError, match="do not match"):
        EvidenceEvaluator().evaluate(dataset, (observation,))
    with pytest.raises(ValueError, match="unique"):
        EvidenceEvaluator().evaluate(dataset, (observation, observation))
def test_v2_requires_quote_and_does_not_score_other_text_in_same_chunk():
    dataset = GoldenQuestionSet.model_validate({"name":"quote-test","version":"v2","retrieval_k":2,"rerank_n":1,
        "questions":[{"question_id":"GQ-001","query":"2024 dividend","expected_evidence":[{"contains_all":["6.80"]}],"rationale":"Annual amount"},
        {"question_id":"GQ-002","query":"2025 dividend","should_refuse":True,"rationale":"Missing source"}]})
    evidence = ObservedEvidence(content="Annual 6.80; interim 3.20",page_start=1,page_end=1,document_title="Public source")
    base = EvaluationObservation(question_id="GQ-001",retrieved=(evidence,),reranked=(evidence,),cited_evidence=evidence,citation_status=CitationStatus.VERIFIED,latency_ms=1)
    refused = EvaluationObservation(question_id="GQ-002",refused=True,latency_ms=1)
    for quote in (None,"interim 3.20"):
        report = EvidenceEvaluator().report(dataset,(base.model_copy(update={"quoted_text":quote}),refused))
        assert not report.cases[0].passed
        assert "citation_not_supported" in report.cases[0].failure_reasons
    assert EvidenceEvaluator().report(dataset,(base.model_copy(update={"quoted_text":"Annual 6.80"}),refused)).cases[0].passed

