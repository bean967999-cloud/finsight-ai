"""Connect the Day16 suite to the established document evidence gold set."""

from finsight.domain.evaluation import (
    EvaluationObservation,
    GoldenQuestionSet,
    RetrievalEvaluationReport,
)
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.services.evidence_evaluation import EvidenceEvaluator


class RetrievalSuiteEvaluator:
    def __init__(self, suite: EvaluationSuite, golden: GoldenQuestionSet) -> None:
        referenced = [item.golden_question_id for item in suite.retrieval_cases]
        expected = [item.question_id for item in golden.questions]
        if len(referenced) != len(set(referenced)) or set(referenced) != set(expected):
            raise ValueError("suite retrieval references must match the golden set exactly")
        self._suite = suite
        self._golden = golden
        self._evaluator = EvidenceEvaluator()

    def report(
        self, observations: tuple[EvaluationObservation, ...] | None = None
    ) -> RetrievalEvaluationReport:
        result = self._evaluator.report(self._golden, observations)
        return result.model_copy(update={
            "suite_name": self._suite.name,
            "suite_version": self._suite.version,
        })
