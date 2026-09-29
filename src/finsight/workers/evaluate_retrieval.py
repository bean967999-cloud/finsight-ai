"""Print a retrieval evaluation report; no observations means explicitly not run."""

from argparse import ArgumentParser
from pathlib import Path

from pydantic import TypeAdapter

from finsight.domain.evaluation import EvaluationObservation, GoldenQuestionSet
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = ArgumentParser(description="Score complete recorded retrieval observations")
    parser.add_argument(
        "--suite", type=Path, default=PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json"
    )
    parser.add_argument(
        "--golden", type=Path, default=PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json"
    )
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    observations = None
    if args.observations is not None:
        observations = TypeAdapter(tuple[EvaluationObservation, ...]).validate_json(
            args.observations.read_text(encoding="utf-8")
        )
    report = RetrievalSuiteEvaluator(
        EvaluationSuite.load(args.suite), GoldenQuestionSet.load(args.golden)
    ).report(observations)
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
