"""Day16 Step1: source-labelled gold labels and scoring tolerances are reviewable."""

from math import isclose
from pathlib import Path

import pytest
from pydantic import ValidationError

from finsight.agents.planning import plan_research
from finsight.domain.evaluation import GoldenQuestionSet
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.domain.research_flow import ResearchQuestion
from finsight.services.risk_engine import RiskEngine

ROOT = Path(__file__).parents[1]
SUITE = ROOT / "Evaluation" / "ResearchSuiteV1.json"


def test_suite_has_unique_reviewable_cases_and_explicit_sources() -> None:
    suite = EvaluationSuite.load(SUITE)
    assert suite.version == "v1"
    assert len(suite.retrieval_cases) == 4
    assert len(suite.tool_cases) == 7
    assert len(suite.numeric_cases) == 4
    ids = [
        case.case_id
        for group in (suite.retrieval_cases, suite.tool_cases, suite.numeric_cases)
        for case in group
    ]
    assert len(ids) == len(set(ids)) == 15
    references = {case.source_ref for case in suite.retrieval_cases}
    assert references == {"Evaluation/GoldenQuestionsV1.json"}
    golden = GoldenQuestionSet.load(ROOT / next(iter(references)))
    assert {case.golden_question_id for case in suite.retrieval_cases} == {
        question.question_id for question in golden.questions
    }
    assert all(case.source.value == "external_document_required" for case in suite.retrieval_cases)
    assert all(case.source.value == "synthetic_fixture" for case in suite.tool_cases)
    assert all(case.source.value == "synthetic_fixture" for case in suite.numeric_cases)


def test_tool_labels_match_inspectable_plans_without_calling_external_tools() -> None:
    for case in EvaluationSuite.load(SUITE).tool_cases:
        plan = plan_research(ResearchQuestion(query=case.query, prices=case.prices))
        assert plan.intent == case.expected_intent, case.case_id
        assert tuple(item.tool for item in plan.items) == case.expected_tools, case.case_id
        assert bool(plan.limitations) == case.expects_limitation, case.case_id


def test_numeric_labels_match_documented_examples_without_aggregate_scoring() -> None:
    for case in EvaluationSuite.load(SUITE).numeric_cases:
        result = RiskEngine.analyze(
            list(case.prices), confidence=case.confidence, trading_days=case.trading_days
        )
        for item in case.expected_metrics:
            observed = getattr(result, item.metric.value)
            assert isclose(
                observed, item.expected, rel_tol=0, abs_tol=item.absolute_tolerance
            ), (case.case_id, item.metric)


def test_suite_rejects_duplicate_ids_invalid_prices_and_loose_or_nonfinite_gold() -> None:
    raw = EvaluationSuite.load(SUITE).model_dump(mode="json")
    raw["tool_cases"][1]["case_id"] = raw["tool_cases"][0]["case_id"]
    with pytest.raises(ValidationError, match="unique"):
        EvaluationSuite.model_validate(raw)

    raw = EvaluationSuite.load(SUITE).model_dump(mode="json")
    raw["numeric_cases"][0]["prices"][1] = 0
    with pytest.raises(ValidationError, match="positive"):
        EvaluationSuite.model_validate(raw)

    raw = EvaluationSuite.load(SUITE).model_dump(mode="json")
    raw["numeric_cases"][0]["expected_metrics"][0]["absolute_tolerance"] = 0.1
    with pytest.raises(ValidationError):
        EvaluationSuite.model_validate(raw)

    raw = EvaluationSuite.load(SUITE).model_dump(mode="json")
    raw["numeric_cases"][0]["expected_metrics"][0]["expected"] = float("nan")
    with pytest.raises(ValidationError, match="finite"):
        EvaluationSuite.model_validate(raw)
