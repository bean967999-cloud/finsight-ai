"""Run real retrieval and source anchoring; persist workspace-scoped observations."""

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from pydantic import BaseModel

from finsight.domain.evaluation import EvaluationObservation, GoldenQuestionSet, ObservedEvidence
from finsight.domain.evaluation_suite import EvaluationSuite
from finsight.services.document_search_filter import DocumentSearchFilter
from finsight.services.evaluation_overview import PROJECT_ROOT
from finsight.services.retrieval_suite_evaluation import RetrievalSuiteEvaluator


class RealDocumentRun(BaseModel):
    workspace_id: UUID
    knowledge_base_id: UUID
    run_id: UUID
    executed_at: datetime
    source: str = "real_local_pdf_retrieval_and_source_anchoring"
    dataset_sha256: str
    observations: tuple[EvaluationObservation, ...]


class EvaluationDatasetChanged(ValueError):
    """A saved result belongs to a different dataset; never reuse its scores."""


class RealDocumentEvaluationService:
    def __init__(self, search, grounded, root: Path, *, golden_path=None, suite_path=None):
        if (golden_path is None) != (suite_path is None):
            raise ValueError("custom golden and suite paths must be configured together")
        self.search, self.grounded, self.root = search, grounded, root
        self.golden_path = golden_path or PROJECT_ROOT / "Evaluation" / "GoldenQuestionsV1.json"
        self.suite_path = suite_path or PROJECT_ROOT / "Evaluation" / "ResearchSuiteV1.json"

    def _dataset(self):
        from hashlib import sha256

        path = self.golden_path
        return GoldenQuestionSet.load(path), sha256(path.read_bytes()).hexdigest()

    def run(self, workspace_id: UUID, knowledge_base_id: UUID):
        golden, digest = self._dataset()
        observations = []
        for question in golden.questions:
            started = perf_counter()
            criteria = DocumentSearchFilter(knowledge_base_id=knowledge_base_id, **question.filters.model_dump())
            result = self.search.search(question.query, criteria=criteria)
            grounded = self.grounded.answer(question.query, knowledge_base_id, criteria=criteria)

            def observed(candidate):
                return ObservedEvidence(
                    content=candidate.content,
                    page_start=candidate.page_start,
                    page_end=candidate.page_end,
                    document_title=candidate.document_title,
                )

            retrieved = tuple(observed(item) for item in result.retrieved)
            reranked = tuple(observed(item.evidence.candidate) for item in result.bundle.citations)
            cited = observed(grounded.citations[0].evidence.candidate) if grounded else None
            # A different search result cannot be inserted into this observed run.
            if cited not in reranked:
                cited = None
            observations.append(
                EvaluationObservation(
                    question_id=question.question_id,
                    retrieved=retrieved,
                    reranked=reranked,
                    refused=grounded is None,
                    cited_evidence=cited,
                    citation_status=grounded.citations[0].status if grounded and cited else None,
                    quoted_text=grounded.citations[0].quoted_text if grounded and cited else None,
                    latency_ms=(perf_counter() - started) * 1000,
                )
            )
        record = RealDocumentRun(
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            run_id=uuid4(),
            executed_at=datetime.now(UTC),
            dataset_sha256=digest,
            observations=tuple(observations),
        )
        self.report(record)  # Validate full observations before publishing a result.
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{workspace_id}.json"
        temporary = self.root / f"{workspace_id}.{record.run_id}.tmp"
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return record

    def load(self, workspace_id: UUID):
        path = self.root / f"{workspace_id}.json"
        if not path.exists():
            return None
        record = RealDocumentRun.model_validate_json(path.read_text(encoding="utf-8"))
        if record.workspace_id != workspace_id:
            raise ValueError("evaluation workspace mismatch")
        _, digest = self._dataset()
        if record.dataset_sha256 != digest:
            raise EvaluationDatasetChanged("evaluation dataset changed; rerun required")
        return record

    def report(self, record):
        golden, digest = self._dataset()
        if record.dataset_sha256 != digest:
            raise EvaluationDatasetChanged("evaluation dataset changed; rerun required")
        suite = EvaluationSuite.load(self.suite_path)
        return RetrievalSuiteEvaluator(suite, golden).report(record.observations)

    def pending_report(self):
        golden, _ = self._dataset()
        suite = EvaluationSuite.load(self.suite_path)
        return RetrievalSuiteEvaluator(suite, golden).report()
