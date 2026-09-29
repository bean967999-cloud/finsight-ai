"""Recompute the local synthetic suite and preserve absent document runs as not-run."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from finsight.agents.planning import plan_research
from finsight.domain.evaluation import GoldenQuestionSet, RetrievalEvaluationReport
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.domain.research_evaluation import (
    NumericObservation,
    ResearchEvaluationReport,
    ToolObservation,
)
from finsight.domain.research_flow import ResearchQuestion
from finsight.services.research_evaluation import ResearchEvaluator
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator
from finsight.services.risk_engine import RiskEngine

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class EvaluationOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    execution: str = "local_synthetic_recomputed_on_request"
    research: ResearchEvaluationReport
    retrieval: RetrievalEvaluationReport
    retrieval_run: dict[str, str] | None = None


def run_suite(suite: EvaluationSuite) -> ResearchEvaluationReport:
    tool_observations = []
    for tool_case in suite.tool_cases:
        plan = plan_research(ResearchQuestion(query=tool_case.query, prices=tool_case.prices))
        tool_observations.append(ToolObservation(
            case_id=tool_case.case_id, intent=plan.intent,
            tools=tuple(item.tool for item in plan.items), limitations=plan.limitations,
        ))
    numeric_observations = []
    for numeric_case in suite.numeric_cases:
        result = RiskEngine.analyze(
            list(numeric_case.prices), confidence=numeric_case.confidence,
            trading_days=numeric_case.trading_days,
        )
        numeric_observations.append(NumericObservation(
            case_id=numeric_case.case_id,
            metrics={
                item.metric: value
                for item in numeric_case.expected_metrics
                if (value := getattr(result, item.metric.value)) is not None
            },
        ))
    return ResearchEvaluator().evaluate(
        suite, tuple(tool_observations), tuple(numeric_observations)
    )


def build_evaluation_overview() -> EvaluationOverview:
    suite = EvaluationSuite.load(PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json")
    golden = GoldenQuestionSet.load(PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json")
    return EvaluationOverview(
        generated_at=datetime.now(UTC),
        research=run_suite(suite),
        retrieval=RetrievalSuiteEvaluator(suite, golden).report(),
    )
