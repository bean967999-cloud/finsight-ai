"""Deterministic metrics for a complete golden-question run."""

from statistics import fmean

from finsight.domain.evaluation import (
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationObservation,
    EvidenceExpectation,
    GoldenQuestion,
    GoldenQuestionSet,
    ObservedEvidence,
    RetrievalEvaluationReport,
)
from finsight.domain.evidence import CitationStatus


class EvidenceEvaluator:
    def report(
        self,
        dataset: GoldenQuestionSet,
        observations: tuple[EvaluationObservation, ...] | None,
    ) -> RetrievalEvaluationReport:
        if observations is None:
            return RetrievalEvaluationReport(
                dataset_name=dataset.name, dataset_version=dataset.version,
                status="not_run",
                unrun_question_ids=tuple(item.question_id for item in dataset.questions),
            )
        metrics = self.evaluate(dataset, observations)
        by_id = {item.question_id: item for item in observations}
        cases: list[EvaluationCaseResult] = []
        for question in dataset.questions:
            observed = by_id[question.question_id]
            retrieval_rank = self._first_relevant_rank(
                question, observed.retrieved[: dataset.retrieval_k]
            )
            rerank_rank = self._first_relevant_rank(
                question, observed.reranked[: dataset.rerank_n]
            )
            citation_correct = self._citation_correct(question, observed, dataset.rerank_n, require_quote=dataset.version != "v1")
            reasons: list[str] = []
            if question.should_refuse:
                if not observed.refused:
                    reasons.append("expected_refusal_missing")
            else:
                if retrieval_rank is None:
                    reasons.append("retrieval_miss")
                if rerank_rank is None:
                    reasons.append("rerank_miss")
                if not citation_correct:
                    reasons.append("citation_not_supported")
                if observed.refused:
                    reasons.append("unexpected_refusal")
            cases.append(EvaluationCaseResult(
                question_id=question.question_id,
                should_refuse=question.should_refuse,
                retrieval_rank=retrieval_rank,
                rerank_rank=rerank_rank,
                citation_correct=citation_correct,
                refused=observed.refused,
                passed=not reasons,
                failure_reasons=tuple(reasons),
            ))
        return RetrievalEvaluationReport(
            dataset_name=dataset.name, dataset_version=dataset.version,
            status="observations_scored", metrics=metrics, cases=tuple(cases),
        )

    def evaluate(
        self,
        dataset: GoldenQuestionSet,
        observations: tuple[EvaluationObservation, ...],
    ) -> EvaluationMetrics:
        by_id = {observation.question_id: observation for observation in observations}
        if len(by_id) != len(observations):
            raise ValueError("evaluation observations must have unique question IDs")
        expected_ids = {question.question_id for question in dataset.questions}
        if set(by_id) != expected_ids:
            missing = sorted(expected_ids - set(by_id))
            unexpected = sorted(set(by_id) - expected_ids)
            raise ValueError(f"observation IDs do not match dataset; missing={missing}, unexpected={unexpected}")
        for observation in observations:
            if any(item not in observation.retrieved for item in observation.reranked):
                raise ValueError("reranked evidence must come from retrieved candidates")

        answerable = [question for question in dataset.questions if not question.should_refuse]
        refusals = [question for question in dataset.questions if question.should_refuse]
        retrieval_hits = 0
        rerank_hits = 0
        reciprocal_ranks: list[float] = []
        correct_citations = 0
        unexpected_refusals = 0

        for question in answerable:
            observation = by_id[question.question_id]
            retrieval_hits += self._first_relevant_rank(
                question, observation.retrieved[: dataset.retrieval_k]
            ) is not None
            final_rank = self._first_relevant_rank(
                question, observation.reranked[: dataset.rerank_n]
            )
            rerank_hits += final_rank is not None
            reciprocal_ranks.append(0.0 if final_rank is None else 1.0 / final_rank)
            correct_citations += self._citation_correct(
                question, observation, dataset.rerank_n, require_quote=dataset.version != "v1"
            )
            unexpected_refusals += observation.refused

        refusal_hits = sum(by_id[item.question_id].refused for item in refusals)
        return EvaluationMetrics(
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            question_count=len(dataset.questions),
            answerable_count=len(answerable),
            refusal_count=len(refusals),
            retrieval_recall_at_k=retrieval_hits / len(answerable),
            rerank_hit_rate_at_n=rerank_hits / len(answerable),
            mean_reciprocal_rank=fmean(reciprocal_ranks),
            citation_correctness=correct_citations / len(answerable),
            refusal_accuracy=refusal_hits / len(refusals),
            unexpected_refusal_rate=unexpected_refusals / len(answerable),
            mean_latency_ms=fmean(item.latency_ms for item in observations),
        )

    @classmethod
    def _citation_correct(
        cls, question: GoldenQuestion, observation: EvaluationObservation, rerank_n: int,
        *, require_quote: bool = False,
    ) -> bool:
        return bool(
            observation.citation_status == CitationStatus.VERIFIED
            and observation.cited_evidence is not None
            and observation.cited_evidence in observation.reranked[:rerank_n]
            and (not require_quote or observation.quoted_text is not None)
            and any(
                cls._matches(expectation, observation.cited_evidence)
                and (observation.quoted_text is None or all(
                    fragment in observation.quoted_text for fragment in expectation.contains_all
                ))
                for expectation in question.expected_evidence
            )
        )

    @classmethod
    def _first_relevant_rank(
        cls,
        question: GoldenQuestion,
        evidence: tuple[ObservedEvidence, ...],
    ) -> int | None:
        for rank, item in enumerate(evidence, start=1):
            if any(cls._matches(expectation, item) for expectation in question.expected_evidence):
                return rank
        return None

    @staticmethod
    def _matches(expectation: EvidenceExpectation, item: ObservedEvidence) -> bool:
        if not all(fragment in item.content for fragment in expectation.contains_all):
            return False
        if (
            expectation.page_number is not None
            and not item.page_start <= expectation.page_number <= item.page_end
        ):
            return False
        return not (
            expectation.document_title_contains is not None
            and expectation.document_title_contains not in item.document_title
        )
