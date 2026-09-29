"""Day16 Step3: score complete tool plans and every labelled numeric metric."""

from pathlib import Path

import pytest

from finsight.agents.planning import plan_research
from finsight.domain.evaluation_suite import EvaluationSuite, MetricName
from finsight.domain.research_evaluation import NumericObservation, ToolObservation
from finsight.domain.research_flow import ResearchQuestion
from finsight.services.research_evaluation import ResearchEvaluator
from finsight.workers.evaluate_research import run_suite

SUITE = EvaluationSuite.load(Path(__file__).parents[1] / "Evaluation" / "ResearchSuiteV1.json")


def _gold_observations():
    tools = tuple(ToolObservation(
        case_id=case.case_id, intent=case.expected_intent,
        tools=case.expected_tools,
        limitations=("expected limitation",) if case.expects_limitation else (),
    ) for case in SUITE.tool_cases)
    numbers = tuple(NumericObservation(
        case_id=case.case_id,
        metrics={item.metric: item.expected for item in case.expected_metrics},
    ) for case in SUITE.numeric_cases)
    return tools, numbers


def test_current_components_pass_only_the_labelled_synthetic_baseline() -> None:
    report = run_suite(SUITE)
    assert report.source == "synthetic_fixture"
    assert report.suite_version == "v1"
    assert report.metrics.tool_case_count == 7
    assert report.metrics.numeric_case_count == 4
    assert report.metrics.numeric_metric_count == 17
    assert report.metrics.tool_case_pass_rate == 1.0
    assert report.metrics.numeric_case_pass_rate == 1.0


def test_missing_price_case_names_the_missing_input_not_just_any_warning() -> None:
    case = next(item for item in SUITE.tool_cases if item.case_id == "D16-T-04")
    plan = plan_research(ResearchQuestion(query=case.query))
    assert "价格序列" in " ".join(plan.limitations)


def test_wrong_tool_missing_limitation_and_numeric_drift_have_separate_failures() -> None:
    tools, numbers = _gold_observations()
    changed_tools = list(tools)
    changed_tools[3] = tools[3].model_copy(update={"limitations": ()})
    changed_tools[4] = tools[4].model_copy(update={"tools": tools[4].tools[:1]})
    changed_numbers = list(numbers)
    changed_numbers[3] = numbers[3].model_copy(update={
        "metrics": {**numbers[3].metrics, MetricName.CUMULATIVE_RETURN: -0.1}
    })
    report = ResearchEvaluator().evaluate(
        SUITE, tuple(changed_tools), tuple(changed_numbers)
    )
    assert report.metrics.tool_set_accuracy == pytest.approx(6 / 7)
    assert report.metrics.limitation_accuracy == pytest.approx(6 / 7)
    assert report.metrics.tool_case_pass_rate == pytest.approx(5 / 7)
    assert report.tool_cases[3].failure_reasons == ("limitation_mismatch",)
    assert report.tool_cases[4].failure_reasons == ("tool_set_mismatch",)
    assert report.metrics.numeric_metric_pass_rate == pytest.approx(16 / 17)
    assert report.metrics.numeric_case_pass_rate == 0.75
    assert report.numeric_cases[3].metrics[0].failure_reason == "outside_tolerance"


def test_missing_nonfinite_and_incomplete_observations_never_pass() -> None:
    tools, numbers = _gold_observations()
    with pytest.raises(ValueError, match="missing"):
        ResearchEvaluator().evaluate(SUITE, tools[:-1], numbers)
    with pytest.raises(ValueError, match="unique"):
        ResearchEvaluator().evaluate(SUITE, tools + (tools[0],), numbers)

    changed = list(numbers)
    changed[0] = numbers[0].model_copy(update={
        "metrics": {
            **numbers[0].metrics,
            MetricName.HISTORICAL_VAR: float("nan"),
        }
    })
    changed[1] = numbers[1].model_copy(update={
        "metrics": {
            metric: value for metric, value in numbers[1].metrics.items()
            if metric != MetricName.ANNUALIZED_VOLATILITY
        }
    })
    report = ResearchEvaluator().evaluate(SUITE, tools, tuple(changed))
    assert report.numeric_cases[0].metrics[2].failure_reason == "non_finite_metric"
    assert report.numeric_cases[1].metrics[4].failure_reason == "missing_metric"
    assert report.metrics.numeric_case_pass_rate == 0.5
