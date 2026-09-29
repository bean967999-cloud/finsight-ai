"""Versioned, source-labelled cases for Day16 cross-component evaluation."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsight.domain.research_flow import ResearchIntent, ResearchTool


class CaseSource(StrEnum):
    SYNTHETIC = "synthetic_fixture"
    EXTERNAL_DOCUMENT = "external_document_required"


class MetricName(StrEnum):
    CUMULATIVE_RETURN = "cumulative_return"
    MAX_DRAWDOWN = "max_drawdown"
    HISTORICAL_VAR = "historical_var"
    HISTORICAL_CVAR = "historical_cvar"
    ANNUALIZED_VOLATILITY = "annualized_volatility"


class RetrievalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^D16-R-[0-9]{2}$")
    golden_question_id: str = Field(pattern=r"^GQ-[0-9]{3}$")
    source: CaseSource
    source_ref: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source(self) -> RetrievalCase:
        if self.source != CaseSource.EXTERNAL_DOCUMENT:
            raise ValueError("retrieval references require a labelled external document")
        return self


class ToolCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(pattern=r"^D16-T-[0-9]{2}$")
    query: str = Field(min_length=2, max_length=2000)
    prices: tuple[float, ...] | None = Field(default=None, min_length=3)
    expected_intent: ResearchIntent
    expected_tools: tuple[ResearchTool, ...]
    expects_limitation: bool = False
    source: CaseSource
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan_label(self) -> ToolCase:
        if self.source != CaseSource.SYNTHETIC:
            raise ValueError("tool cases must identify their synthetic source")
        if self.prices is not None and any(not isfinite(x) or x <= 0 for x in self.prices):
            raise ValueError("prices must be finite and positive")
        if len(self.expected_tools) != len(set(self.expected_tools)):
            raise ValueError("expected tools must be unique")
        if (self.expected_intent == ResearchIntent.UNSUPPORTED) != (not self.expected_tools):
            raise ValueError("unsupported intent must have no tools; supported intent needs tools")
        if self.expected_intent == ResearchIntent.UNSUPPORTED and not self.expects_limitation:
            raise ValueError("unsupported requests require a limitation")
        if (
            ResearchTool.RISK_CALCULATION in self.expected_tools
            and self.prices is None
            and not self.expects_limitation
        ):
            raise ValueError("risk requests without prices require a limitation")
        return self


class MetricExpectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: MetricName
    expected: float
    absolute_tolerance: float = Field(ge=0, le=0.01)
    calculation_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def finite_values(self) -> MetricExpectation:
        if not isfinite(self.expected) or not isfinite(self.absolute_tolerance):
            raise ValueError("numeric expectations must be finite")
        return self


class NumericCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^D16-N-[0-9]{2}$")
    prices: tuple[float, ...] = Field(min_length=3)
    confidence: float = Field(gt=0.5, lt=1)
    trading_days: int = Field(gt=0, le=366)
    expected_metrics: tuple[MetricExpectation, ...] = Field(min_length=1)
    source: CaseSource
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_numeric_case(self) -> NumericCase:
        if self.source != CaseSource.SYNTHETIC:
            raise ValueError("numeric cases must identify their synthetic source")
        if any(not isfinite(x) or x <= 0 for x in self.prices):
            raise ValueError("prices must be finite and positive")
        names = [item.metric for item in self.expected_metrics]
        if len(names) != len(set(names)):
            raise ValueError("numeric metric labels must be unique")
        return self


class EvaluationSuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    retrieval_cases: tuple[RetrievalCase, ...] = Field(min_length=1)
    tool_cases: tuple[ToolCase, ...] = Field(min_length=1)
    numeric_cases: tuple[NumericCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> EvaluationSuite:
        ids = [
            item.case_id
            for group in (self.retrieval_cases, self.tool_cases, self.numeric_cases)
            for item in group
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self

    @classmethod
    def load(cls, path: Path) -> EvaluationSuite:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
