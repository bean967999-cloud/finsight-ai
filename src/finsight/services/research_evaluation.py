"""Exact-set tool scoring and tolerance-bounded deterministic numeric scoring."""

from collections.abc import Sequence
from math import isfinite

from finsight.domain.evaluation_suite import EvaluationSuite, MetricExpectation
from finsight.domain.research_evaluation import (
    NumericCaseResult,
    NumericMetricResult,
    NumericObservation,
    ResearchEvaluationMetrics,
    ResearchEvaluationReport,
    ToolCaseResult,
    ToolObservation,
)


def _validate_observation_ids(
    items: Sequence[ToolObservation | NumericObservation],
    expected_ids: set[str], *, kind: str,
) -> None:
    by_id = {item.case_id for item in items}
    if len(by_id) != len(items):
        raise ValueError(f"{kind} observation IDs must be unique")
    if by_id != expected_ids:
        missing = sorted(expected_ids - by_id)
        unexpected = sorted(by_id - expected_ids)
        raise ValueError(f"{kind} observations do not match suite; missing={missing}, unexpected={unexpected}")


def _metric_result(expectation: MetricExpectation, observed: float | None) -> NumericMetricResult:
    if observed is None:
        return NumericMetricResult(
            metric=expectation.metric, expected=expectation.expected,
            observed=None, absolute_tolerance=expectation.absolute_tolerance,
            absolute_error=None, passed=False, failure_reason="missing_metric",
        )
    if not isfinite(observed):
        return NumericMetricResult(
            metric=expectation.metric, expected=expectation.expected,
            observed=None, absolute_tolerance=expectation.absolute_tolerance,
            absolute_error=None, passed=False, failure_reason="non_finite_metric",
        )
    error = abs(observed - expectation.expected)
    passed = error <= expectation.absolute_tolerance
    return NumericMetricResult(
        metric=expectation.metric, expected=expectation.expected,
        observed=observed, absolute_tolerance=expectation.absolute_tolerance,
        absolute_error=error, passed=passed,
        failure_reason=None if passed else "outside_tolerance",
    )


class ResearchEvaluator:
    def evaluate(
        self,
        suite: EvaluationSuite,
        tool_observations: tuple[ToolObservation, ...],
        numeric_observations: tuple[NumericObservation, ...],
    ) -> ResearchEvaluationReport:
        _validate_observation_ids(
            tool_observations, {case.case_id for case in suite.tool_cases}, kind="tool"
        )
        _validate_observation_ids(
            numeric_observations, {case.case_id for case in suite.numeric_cases}, kind="numeric"
        )
        tools = {item.case_id: item for item in tool_observations}
        numbers = {item.case_id: item for item in numeric_observations}
        tool_results: list[ToolCaseResult] = []
        for tool_case in suite.tool_cases:
            observed_tool = tools[tool_case.case_id]
            intent_correct = observed_tool.intent == tool_case.expected_intent
            tool_set_correct = set(observed_tool.tools) == set(tool_case.expected_tools)
            limitation_correct = bool(observed_tool.limitations) == tool_case.expects_limitation
            reasons = tuple(
                reason for passed, reason in (
                    (intent_correct, "intent_mismatch"),
                    (tool_set_correct, "tool_set_mismatch"),
                    (limitation_correct, "limitation_mismatch"),
                ) if not passed
            )
            tool_results.append(ToolCaseResult(
                case_id=tool_case.case_id, intent_correct=intent_correct,
                tool_set_correct=tool_set_correct, limitation_correct=limitation_correct,
                passed=not reasons, failure_reasons=reasons,
            ))

        numeric_results: list[NumericCaseResult] = []
        for numeric_case in suite.numeric_cases:
            observed_numeric = numbers[numeric_case.case_id]
            metrics = tuple(
                _metric_result(item, observed_numeric.metrics.get(item.metric))
                for item in numeric_case.expected_metrics
            )
            numeric_results.append(NumericCaseResult(
                case_id=numeric_case.case_id, metrics=metrics,
                passed=all(item.passed for item in metrics),
            ))
        metric_results = [item for case in numeric_results for item in case.metrics]
        return ResearchEvaluationReport(
            suite_name=suite.name, suite_version=suite.version,
            metrics=ResearchEvaluationMetrics(
                tool_case_count=len(tool_results),
                intent_accuracy=sum(item.intent_correct for item in tool_results) / len(tool_results),
                tool_set_accuracy=sum(item.tool_set_correct for item in tool_results) / len(tool_results),
                limitation_accuracy=sum(item.limitation_correct for item in tool_results) / len(tool_results),
                tool_case_pass_rate=sum(item.passed for item in tool_results) / len(tool_results),
                numeric_case_count=len(numeric_results),
                numeric_metric_count=len(metric_results),
                numeric_metric_pass_rate=sum(item.passed for item in metric_results) / len(metric_results),
                numeric_case_pass_rate=sum(item.passed for item in numeric_results) / len(numeric_results),
            ),
            tool_cases=tuple(tool_results), numeric_cases=tuple(numeric_results),
        )
