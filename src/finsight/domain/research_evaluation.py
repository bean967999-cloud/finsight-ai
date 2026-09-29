"""Observed tool plans and numeric results, separate from immutable gold labels."""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.evaluation_suite import MetricName
from finsight.domain.research_flow import ResearchIntent, ResearchTool


class ToolObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^D16-T-[0-9]{2}$")
    intent: ResearchIntent
    tools: tuple[ResearchTool, ...]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_tools(self) -> ToolObservation:
        if len(self.tools) != len(set(self.tools)):
            raise ValueError("observed tools must be unique")
        return self


class NumericObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^D16-N-[0-9]{2}$")
    metrics: dict[MetricName, float]


class ToolCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    intent_correct: bool
    tool_set_correct: bool
    limitation_correct: bool
    passed: bool
    failure_reasons: tuple[str, ...]


class NumericMetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: MetricName
    expected: float
    observed: float | None
    absolute_tolerance: float
    absolute_error: float | None
    passed: bool
    failure_reason: str | None

    @model_validator(mode="after")
    def validate_error(self) -> NumericMetricResult:
        if self.observed is not None and not isfinite(self.observed):
            # Preserve a finite JSON report even if the tool emitted NaN or infinity.
            raise ValueError("reported observed value must be finite")
        return self


class NumericCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    metrics: tuple[NumericMetricResult, ...]
    passed: bool


class ResearchEvaluationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_case_count: int
    intent_accuracy: float
    tool_set_accuracy: float
    limitation_accuracy: float
    tool_case_pass_rate: float
    numeric_case_count: int
    numeric_metric_count: int
    numeric_metric_pass_rate: float
    numeric_case_pass_rate: float


class ResearchEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite_name: str
    suite_version: str
    source: Literal["synthetic_fixture"] = "synthetic_fixture"
    metrics: ResearchEvaluationMetrics
    tool_cases: tuple[ToolCaseResult, ...]
    numeric_cases: tuple[NumericCaseResult, ...]
