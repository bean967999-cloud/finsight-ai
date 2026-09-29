"""Day16 Step6: honest local acceptance with explicit unrun retrieval coverage."""

import pytest

from finsight.domain.evaluation import GoldenQuestionSet
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.workers.day16_acceptance import PROJECT_ROOT, run_acceptance


def test_local_acceptance_keeps_external_retrieval_unrun() -> None:
    suite = EvaluationSuite.load(PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json")
    golden = GoldenQuestionSet.load(PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json")
    report = run_acceptance(suite, golden, warmup_rounds=1, measured_rounds=10)
    assert report.status == "local_pass_partial_coverage"
    assert (report.synthetic_tool_passed, report.synthetic_tool_total) == (7, 7)
    assert (report.synthetic_numeric_passed, report.synthetic_numeric_total) == (4, 4)
    assert report.retrieval_status == "not_run" and report.retrieval_unrun == 4
    assert report.planning_timing.samples == 70
    assert report.risk_timing.samples == 40
    assert report.planning_timing.p50_ms <= report.planning_timing.p95_ms
    assert report.risk_timing.p95_ms <= report.risk_timing.max_ms
    assert report.api_latency is None and report.external_services == "not_used"


def test_invalid_measurement_counts_rejected() -> None:
    suite = EvaluationSuite.load(PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json")
    golden = GoldenQuestionSet.load(PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json")
    with pytest.raises(ValueError, match="measured rounds"):
        run_acceptance(suite, golden, measured_rounds=0)
