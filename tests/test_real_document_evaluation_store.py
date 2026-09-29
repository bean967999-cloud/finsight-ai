from datetime import UTC, datetime
from uuid import uuid4

import pytest

from finsight.services.real_document_evaluation import (
    RealDocumentEvaluationService,
    RealDocumentRun,
)


def test_absent_run_stays_absent(tmp_path):
    assert RealDocumentEvaluationService(None, None, tmp_path).load(uuid4()) is None


def test_store_rejects_wrong_workspace_and_changed_dataset(tmp_path):
    service = RealDocumentEvaluationService(None, None, tmp_path)
    workspace = uuid4()
    _, digest = service._dataset()
    record = RealDocumentRun(
        workspace_id=uuid4(),
        knowledge_base_id=uuid4(),
        run_id=uuid4(),
        executed_at=datetime.now(UTC),
        dataset_sha256=digest,
        observations=(),
    )
    path = tmp_path / f"{workspace}.json"
    path.write_text(record.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="workspace mismatch"):
        service.load(workspace)
    record = record.model_copy(update={"workspace_id": workspace, "dataset_sha256": "0" * 64})
    path.write_text(record.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset changed"):
        service.load(workspace)


def test_incomplete_observations_cannot_be_scored(tmp_path):
    service = RealDocumentEvaluationService(None, None, tmp_path)
    _, digest = service._dataset()
    record = RealDocumentRun(
        workspace_id=uuid4(),
        knowledge_base_id=uuid4(),
        run_id=uuid4(),
        executed_at=datetime.now(UTC),
        dataset_sha256=digest,
        observations=(),
    )
    with pytest.raises(ValueError, match="observation IDs"):
        service.report(record)


def test_custom_paths_are_paired_and_pending_report_uses_current_dataset(tmp_path):
    from pathlib import Path
    root = Path(__file__).parents[1] / "Evaluation"
    with pytest.raises(ValueError, match="configured together"):
        RealDocumentEvaluationService(None, None, tmp_path, golden_path=root / "GoldenQuestionsV1.json")
    service = RealDocumentEvaluationService(None, None, tmp_path,
        golden_path=root / "GoldenQuestionsV1.json", suite_path=root / "ResearchSuiteV1.json")
    report = service.pending_report()
    assert report.status == "not_run" and len(report.unrun_question_ids) == 4


def test_run_uses_identical_filters_for_search_and_answer(tmp_path):
    from types import SimpleNamespace

    from finsight.domain.evidence import CitationStatus

    search_filters, answer_filters = [], []
    service = RealDocumentEvaluationService(None, None, tmp_path)
    golden, _ = service._dataset()
    def search(query, *, criteria):
        search_filters.append(criteria)
        expected = next(q for q in golden.questions if q.query == query)
        if expected.should_refuse:
            return SimpleNamespace(retrieved=(), bundle=SimpleNamespace(citations=()))
        e = expected.expected_evidence[0]
        candidate = SimpleNamespace(content=" ".join(e.contains_all), page_start=e.page_number, page_end=e.page_number, document_title="Public source")
        return SimpleNamespace(retrieved=(candidate,), bundle=SimpleNamespace(citations=(SimpleNamespace(evidence=SimpleNamespace(candidate=candidate)),)))
    def answer(query, kb, *, criteria):
        answer_filters.append(criteria)
        result = search(query, criteria=criteria)
        if not result.retrieved:
            return None
        c = result.retrieved[0]
        return SimpleNamespace(citations=(SimpleNamespace(evidence=SimpleNamespace(candidate=c), status=CitationStatus.VERIFIED, quoted_text=c.content),))
    service.search = SimpleNamespace(search=search)
    service.grounded = SimpleNamespace(answer=answer)
    record = service.run(uuid4(), uuid4())
    assert tuple(search_filters[::2]) == tuple(answer_filters)
    assert len(record.observations) == 4
    assert all(o.quoted_text for o in record.observations if not o.refused)
    assert all(case.passed for case in service.report(record).cases)
