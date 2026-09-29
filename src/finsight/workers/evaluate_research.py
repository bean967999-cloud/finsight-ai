"""Run the synthetic planning and numeric baseline without external services."""

from argparse import ArgumentParser
from pathlib import Path

from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.services.evaluation_overview import run_suite

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = ArgumentParser(description="Run the synthetic research evaluation baseline")
    parser.add_argument(
        "--suite", type=Path, default=PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json"
    )
    args = parser.parse_args()
    report = run_suite(EvaluationSuite.load(args.suite))
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
