"""Day16 Step2: complete observations or an honest not-run report."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from finsight.domain.evaluation import EvaluationObservation, GoldenQuestionSet, ObservedEvidence
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.domain.evidence import CitationStatus
from finsight.services.evidence_evaluation import EvidenceEvaluator
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator
from finsight.workers.evaluate_retrieval import main

ROOT = Path(__file__).parents[1]


def _evidence(text: str, page: int) -> ObservedEvidence:
    return ObservedEvidence(
        content=text, page_start=page, page_end=page,
        document_title="Public financial disclosure excerpt",
    )


def _runner() -> RetrievalSuiteEvaluator:
    return RetrievalSuiteEvaluator(
        EvaluationSuite.load(ROOT / "Evaluation" / "ResearchSuiteV1.json"),
        GoldenQuestionSet.load(ROOT / "Evaluation" / "GoldenQuestionsV1.json"),
    )


def test_missing_document_observations_are_not_reported_as_success() -> None:
    report = _runner().report()
    assert report.status == "not_run"
    assert report.metrics is None and report.cases == ()
    assert report.unrun_question_ids == ("GQ-001", "GQ-002", "GQ-003", "GQ-004")
    assert report.suite_version == "v1"


def test_case_report_explains_retrieval_rerank_citation_and_refusal() -> None:
    first = _evidence("assets were 1,396,927", 2)
    second = _evidence("dividend per share was 6.80", 1)
    third = _evidence("increase was 26%", 1)
    wrong = _evidence("unrelated information", 9)
    observations = (
        EvaluationObservation(
            question_id="GQ-001", retrieved=(wrong, first), reranked=(first,),
            cited_evidence=first, citation_status=CitationStatus.VERIFIED, latency_ms=10,
        ),
        EvaluationObservation(
            question_id="GQ-002", retrieved=(second, wrong), reranked=(wrong,),
            cited_evidence=wrong, citation_status=CitationStatus.VERIFIED, latency_ms=20,
        ),
        EvaluationObservation(
            question_id="GQ-003", retrieved=(wrong,), reranked=(wrong,), latency_ms=30,
        ),
        EvaluationObservation(question_id="GQ-004", refused=True, latency_ms=40),
    )
    report = _runner().report(observations)
    assert report.status == "observations_scored"
    assert report.metrics is not None
    assert report.metrics.retrieval_recall_at_k == pytest.approx(2 / 3)
    assert report.metrics.rerank_hit_rate_at_n == pytest.approx(1 / 3)
    assert report.metrics.citation_correctness == pytest.approx(1 / 3)
    assert report.metrics.refusal_accuracy == 1.0
    assert report.cases[0].passed
    assert report.cases[0].retrieval_rank == 2 and report.cases[0].rerank_rank == 1
    assert report.cases[1].failure_reasons == ("rerank_miss", "citation_not_supported")
    assert report.cases[2].failure_reasons == (
        "retrieval_miss", "rerank_miss", "citation_not_supported",
    )
    assert report.cases[3].passed
    assert third not in observations[2].retrieved


def test_incomplete_or_inconsistent_observations_fail_closed() -> None:
    with pytest.raises(ValueError, match="do not match"):
        _runner().report((EvaluationObservation(question_id="GQ-001", latency_ms=1),))
    wrong = _evidence("unrelated", 2)
    with pytest.raises(ValidationError, match="supplied together"):
        EvaluationObservation(
            question_id="GQ-001", reranked=(wrong,),
            citation_status=CitationStatus.VERIFIED, latency_ms=1,
        )
    with pytest.raises(ValidationError, match="present in reranked"):
        EvaluationObservation(
            question_id="GQ-001", reranked=(), cited_evidence=wrong,
            citation_status=CitationStatus.VERIFIED, latency_ms=1,
        )


def test_command_without_observations_prints_not_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_retrieval"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "not_run"
    assert output["metrics"] is None


def test_verified_citation_outside_final_top_n_is_not_correct() -> None:
    question = GoldenQuestionSet.load(
        ROOT / "Evaluation" / "GoldenQuestionsV1.json"
    ).questions[0]
    wrong = _evidence("unrelated", 9)
    relevant = _evidence("assets were 1,396,927", 2)
    observation = EvaluationObservation(
        question_id=question.question_id,
        retrieved=(wrong, relevant), reranked=(wrong, relevant),
        cited_evidence=relevant, citation_status=CitationStatus.VERIFIED,
        latency_ms=1,
    )
    assert not EvidenceEvaluator._citation_correct(question, observation, rerank_n=1)
