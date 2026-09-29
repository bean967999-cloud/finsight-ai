"""Review endpoints are guarded and expose only workflow metadata."""

from uuid import uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.main import app

_QUESTION = {
    "query": "计算价格波动率",
    "prices": [100, 102, 101, 105],
    "release_requested": True,
}


def test_review_endpoints_fail_closed_without_identity_service() -> None:
    client = TestClient(app)
    assert client.post("/api/v1/agent/query", json=_QUESTION).status_code == 503
    assert client.post(
        "/api/v1/agent/query", headers={"X-Review-Key": "old-shared-key"}, json=_QUESTION
    ).status_code == 503
    assert client.get(f"/api/v1/agent/threads/{uuid4()}").status_code == 503
    assert client.post(
        f"/api/v1/agent/threads/{uuid4()}/review", json={"choice": "confirmed"}
    ).status_code == 503


def test_review_workflow_auth_errors_and_duplicate_decision(agent_auth) -> None:
    service = ResearchCheckpointService(InMemorySaver())
    app.state.research_checkpoints = service
    try:
        client = TestClient(app)
        question = {**_QUESTION, "workspace_id": str(agent_auth.workspace_id)}
        assert client.post("/api/v1/agent/query", json=question).status_code == 401
        assert client.post(
            "/api/v1/agent/query", headers={"Authorization": "Bearer wrong"}, json=question
        ).status_code == 401
        created = client.post(
            "/api/v1/agent/query", headers=agent_auth.headers(), json=question
        )
        assert created.status_code == 200
        thread_id = created.json()["thread_id"]
        path = f"/api/v1/agent/threads/{thread_id}"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=agent_auth.headers()).status_code == 403
        pending = client.get(path, headers=agent_auth.headers("reviewer"))
        assert pending.status_code == 200
        assert pending.json()["phase"] == "awaiting_review"
        assert "prices" not in pending.json()
        assert "risk_metrics" not in pending.json()
        assert "answer" not in pending.json()
        assert client.get(f"{path}/content", headers=agent_auth.headers()).status_code == 403
        content = client.get(f"{path}/content", headers=agent_auth.headers("reviewer"))
        assert content.status_code == 200
        assert content.json()["answer"] == service.get(thread_id).answer_result.text
        assert "prices" not in content.json()
        assert content.json()["citations"] == []
        assert client.get("/api/v1/agent/threads/not-a-uuid", headers=agent_auth.headers("reviewer")).status_code == 422
        assert client.get(f"/api/v1/agent/threads/{uuid4()}", headers=agent_auth.headers("reviewer")).status_code == 404
        assert client.post(
            f"{path}/review", headers=agent_auth.headers("reviewer"), json={"choice": "rejected"}
        ).status_code == 422
        completed = client.post(
            f"{path}/review",
            headers=agent_auth.headers("reviewer"),
            json={"choice": "rejected", "note": "价格样本来源需要复核"},
        )
        assert completed.status_code == 200
        assert completed.json()["phase"] == "finished"
        assert completed.json()["answer_status"] == "insufficient_evidence"
        assert completed.json()["review_outcome"]["choice"] == "rejected"
        assert client.post(
            f"{path}/review", headers=agent_auth.headers("reviewer"), json={"choice": "confirmed"}
        ).status_code == 409
        assert client.get(path, headers=agent_auth.headers("reviewer")).json() == completed.json()
    finally:
        del app.state.research_checkpoints


def test_review_endpoint_checks_missing_service_and_non_pending_flow(agent_auth) -> None:
    try:
        client = TestClient(app)
        headers = agent_auth.headers("reviewer")
        assert client.get(f"/api/v1/agent/threads/{uuid4()}", headers=headers).status_code == 503
        assert client.post(
            f"/api/v1/agent/threads/{uuid4()}/review",
            headers=headers,
            json={"choice": "confirmed"},
        ).status_code == 503
        service = ResearchCheckpointService(InMemorySaver())
        app.state.research_checkpoints = service
        ordinary = service.start({
            "query": "计算价格波动率", "prices": [100, 102, 101, 105],
            "workspace_id": str(agent_auth.workspace_id),
            "owner_user_id": str(agent_auth.researcher_id),
        })
        assert client.post(
            f"/api/v1/agent/threads/{ordinary.thread_id}/review",
            headers=headers,
            json={"choice": "confirmed"},
        ).status_code == 409
        assert client.post(
            f"/api/v1/agent/threads/{uuid4()}/review",
            headers=headers,
            json={"choice": "confirmed"},
        ).status_code == 404
        assert client.post(
            "/api/v1/agent/threads/invalid/review",
            headers=headers,
            json={"choice": "confirmed"},
        ).status_code == 422
    finally:
        if hasattr(app.state, "research_checkpoints"):
            del app.state.research_checkpoints
