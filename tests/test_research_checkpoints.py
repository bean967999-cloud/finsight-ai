"""Day14 Step2: thread identity and checkpoint readback without PostgreSQL."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from finsight.agents.checkpoints import (
    ResearchCheckpointService,
    ReviewConflictError,
    ReviewNotFoundError,
)
from finsight.agents.snapshot import ResearchPhase
from finsight.domain.research_review import ReviewChoice, ReviewDecision
from finsight.main import app


def test_server_generated_thread_id_and_saved_state_are_stable() -> None:
    saver = InMemorySaver()
    service = ResearchCheckpointService(saver)
    run = service.start({"query": "计算价格波动率", "prices": [100, 102, 101, 105]})
    UUID(run.thread_id)
    assert run.snapshot.phase == ResearchPhase.FINISHED
    assert run.snapshot.risk_metrics is not None
    assert service.get(run.thread_id) == run.snapshot
    assert service.get(str(uuid4())) is None

    rebuilt = ResearchCheckpointService(saver)
    restored = rebuilt.get(run.thread_id)
    assert restored is not None
    assert restored.answer_result == run.snapshot.answer_result
    assert restored.question.query == "计算价格波动率"


def test_http_returns_server_generated_thread_id_when_checkpointer_is_active(agent_auth) -> None:
    service = ResearchCheckpointService(InMemorySaver())
    app.state.research_checkpoints = service
    try:
        response = TestClient(app).post(
            "/api/v1/agent/query",
            headers=agent_auth.headers(),
            json={"query": "计算价格波动率", "prices": [100, 102, 101, 105], "workspace_id": str(agent_auth.workspace_id)},
        )
    finally:
        del app.state.research_checkpoints
    assert response.status_code == 200
    thread_id = response.json()["thread_id"]
    UUID(thread_id)
    saved = service.get(thread_id)
    assert saved is not None and saved.answer_result is not None
    assert saved.answer_result.text == response.json()["answer"]


def test_release_request_pauses_and_can_be_read_back_without_releasing_result(agent_auth) -> None:
    service = ResearchCheckpointService(InMemorySaver())
    app.state.research_checkpoints = service
    try:
        response = TestClient(app).post(
            "/api/v1/agent/query",
            headers=agent_auth.headers(),
            json={
                "query": "计算价格波动率",
                "prices": [100, 102, 101, 105],
                "release_requested": True,
                "workspace_id": str(agent_auth.workspace_id),
            },
        )
    finally:
        del app.state.research_checkpoints
    assert response.status_code == 200
    body = response.json()
    assert body["review_pending"] is True
    assert body["risk_metrics"] is None
    assert body["answer"] == "流程已暂停，等待人工确认；尚未对外定稿。"
    assert body["review_request"]["answer_status"] == "insufficient_evidence"
    saved = service.get(body["thread_id"])
    assert saved is not None
    assert saved.phase == ResearchPhase.AWAITING_REVIEW
    assert saved.model_dump_json() == saved.model_validate_json(saved.model_dump_json()).model_dump_json()


def test_release_request_requires_persistent_service(agent_auth) -> None:
    response = TestClient(app).post(
        "/api/v1/agent/query",
        headers=agent_auth.headers(),
        json={"query": "计算价格波动率", "prices": [100, 102, 101, 105], "release_requested": True, "workspace_id": str(agent_auth.workspace_id)},
    )
    assert response.status_code == 503


@pytest.mark.parametrize("choice", [ReviewChoice.CONFIRMED, ReviewChoice.REJECTED])
def test_resume_preserves_answer_status_and_rejects_duplicate(choice: ReviewChoice) -> None:
    saver = InMemorySaver()
    service = ResearchCheckpointService(saver)
    pending = service.start(
        {"query": "计算价格波动率", "prices": [100, 102, 101, 105], "release_requested": True}
    )
    decision = ReviewDecision(choice=choice, note="已阅读局限")
    rebuilt = ResearchCheckpointService(saver)
    finished = rebuilt.resume(pending.thread_id, decision)
    assert finished.snapshot.phase == ResearchPhase.FINISHED
    assert finished.snapshot.review_outcome == decision.model_dump(mode="json")
    assert finished.snapshot.answer_result == pending.snapshot.answer_result
    assert rebuilt.get(pending.thread_id) == finished.snapshot
    with pytest.raises(ReviewConflictError):
        service.resume(pending.thread_id, decision)


def test_resume_requires_existing_pending_flow_and_valid_decision() -> None:
    service = ResearchCheckpointService(InMemorySaver())
    with pytest.raises(ReviewNotFoundError):
        service.resume(str(uuid4()), ReviewDecision(choice=ReviewChoice.CONFIRMED))
    normal = service.start({"query": "计算价格波动率", "prices": [100, 102, 101, 105]})
    with pytest.raises(ReviewConflictError):
        service.resume(normal.thread_id, ReviewDecision(choice=ReviewChoice.CONFIRMED))
    with pytest.raises(ValueError, match="rejection requires a reason"):
        ReviewDecision(choice=ReviewChoice.REJECTED)
