"""Reproducible local Day16 acceptance and synthetic microbenchmark."""

from __future__ import annotations

import platform
from argparse import ArgumentParser
from math import ceil
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from finsight.agents.planning import plan_research
from finsight.domain.evaluation import GoldenQuestionSet
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.domain.research_flow import ResearchQuestion
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator
from finsight.services.risk_engine import RiskEngine
from finsight.workers.evaluate_research import run_suite

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class StageTiming(BaseModel):
    model_config = ConfigDict(frozen=True)

    samples: int = Field(gt=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class LocalAcceptanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite_version: str
    status: str
    synthetic_tool_passed: int
    synthetic_tool_total: int
    synthetic_numeric_passed: int
    synthetic_numeric_total: int
    retrieval_status: str
    retrieval_unrun: int
    warmup_rounds: int
    measured_rounds: int
    execution: str = "single_process_sequential_offline"
    python_version: str
    os_system: str
    os_machine: str
    planning_timing: StageTiming
    risk_timing: StageTiming
    api_latency: None = None
    external_services: str = "not_used"


def _stage_timing(samples: list[float]) -> StageTiming:
    ordered = sorted(samples)
    return StageTiming(
        samples=len(ordered),
        p50_ms=ordered[ceil(len(ordered) * 0.5) - 1],
        p95_ms=ordered[ceil(len(ordered) * 0.95) - 1],
        max_ms=ordered[-1],
    )


def run_acceptance(
    suite: EvaluationSuite, golden: GoldenQuestionSet, *, warmup_rounds: int = 5,
    measured_rounds: int = 100,
) -> LocalAcceptanceReport:
    if warmup_rounds < 0 or not 10 <= measured_rounds <= 10000:
        raise ValueError("warmups must be non-negative and measured rounds must be 10..10000")

    research = run_suite(suite)
    retrieval = RetrievalSuiteEvaluator(suite, golden).report()
    plan_times: list[float] = []
    risk_times: list[float] = []
    for round_number in range(warmup_rounds + measured_rounds):
        measured = round_number >= warmup_rounds
        for tool_case in suite.tool_cases:
            started = perf_counter()
            plan_research(ResearchQuestion(query=tool_case.query, prices=tool_case.prices))
            if measured:
                plan_times.append((perf_counter() - started) * 1000)
        for numeric_case in suite.numeric_cases:
            started = perf_counter()
            RiskEngine.analyze(
                list(numeric_case.prices), confidence=numeric_case.confidence,
                trading_days=numeric_case.trading_days,
            )
            if measured:
                risk_times.append((perf_counter() - started) * 1000)

    tool_passed = sum(item.passed for item in research.tool_cases)
    numeric_passed = sum(item.passed for item in research.numeric_cases)
    local_passed = (
        tool_passed == len(suite.tool_cases)
        and numeric_passed == len(suite.numeric_cases)
    )
    status = "local_pass_partial_coverage" if local_passed else "local_failed"
    return LocalAcceptanceReport(
        suite_version=suite.version,
        status=status,
        synthetic_tool_passed=tool_passed,
        synthetic_tool_total=len(suite.tool_cases),
        synthetic_numeric_passed=numeric_passed,
        synthetic_numeric_total=len(suite.numeric_cases),
        retrieval_status=retrieval.status,
        retrieval_unrun=len(retrieval.unrun_question_ids),
        warmup_rounds=warmup_rounds,
        measured_rounds=measured_rounds,
        python_version=platform.python_version(),
        os_system=platform.system(),
        os_machine=platform.machine(),
        planning_timing=_stage_timing(plan_times),
        risk_timing=_stage_timing(risk_times),
    )


def main() -> int:
    parser = ArgumentParser(description="Run local Day16 acceptance and microbenchmark")
    parser.add_argument("--suite", type=Path, default=PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json")
    parser.add_argument("--golden", type=Path, default=PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json")
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=100)
    args = parser.parse_args()
    report = run_acceptance(
        EvaluationSuite.load(args.suite), GoldenQuestionSet.load(args.golden),
        warmup_rounds=args.warmups, measured_rounds=args.rounds,
    )
    print(report.model_dump_json(indent=2))
    return 1 if report.status == "local_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
