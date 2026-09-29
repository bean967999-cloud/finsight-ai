"""Stored traces retain safe ordering and enforce current workspace/owner access."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.domain.access_control import ResourceScope
from finsight.infrastructure.database.models.research_trace import ResearchTrace
from finsight.main import app
from finsight.services.research_trace_store import CaptureTraceSink, ResearchTraceStore
from finsight.services.structured_trace import TraceEvent, TraceKind


def test_research_trace_persists_safe_events_and_blocks_foreign_scope(agent_auth) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ResearchTrace.__table__.create(engine)
    store = ResearchTraceStore(sessionmaker(bind=engine))
    app.state.research_trace_store = store
    try:
        client = TestClient(app)
        created = client.post("/api/v1/agent/query", headers=agent_auth.headers(), json={
            "query": "计算风险 PRIVATE_TRACE_QUERY", "prices": [100, 101, 99, 102],
            "workspace_id": str(agent_auth.workspace_id),
        })
        assert created.status_code == 200
        assert created.headers["X-Trace-Status"] == "stored"
        request_id = created.headers["X-Request-ID"]
        path = f"/api/v1/agent/traces/{request_id}"
        assert client.get(path).status_code == 401
        response = client.get(path, headers=agent_auth.headers())
        assert response.status_code == 200
        frames = response.json()["frames"]
        assert [item["sequence"] for item in frames] == list(range(1, len(frames) + 1))
        kinds = [item["event"]["kind"] for item in frames]
        assert "research_plan" in kinds and "tool_completed" in kinds
        assert kinds[-1] == "http_completed"
        assert "PRIVATE_TRACE_QUERY" not in response.text
        assert "test-researcher-token" not in response.text
        assert client.get(path, headers=agent_auth.headers("reviewer")).status_code == 200

        for workspace, owner, knowledge in (
            (uuid4(), agent_auth.researcher_id, None),
            (agent_auth.workspace_id, uuid4(), None),
            (agent_auth.workspace_id, agent_auth.researcher_id, uuid4()),
        ):
            foreign_id = uuid4()
            capture = CaptureTraceSink(None)
            capture.emit(TraceEvent(request_id=foreign_id, kind=TraceKind.HTTP_COMPLETED))
            store.save(foreign_id, ResourceScope(
                workspace_id=workspace, owner_user_id=owner, knowledge_base_id=knowledge,
            ), capture)
            assert client.get(f"/api/v1/agent/traces/{foreign_id}", headers=agent_auth.headers()).status_code == 403
        assert client.get(f"/api/v1/agent/traces/{uuid4()}", headers=agent_auth.headers()).status_code == 404
        saved = store.get(UUID(request_id))
        assert saved is not None and saved.truncated is False
    finally:
        del app.state.research_trace_store
        engine.dispose()


def test_capture_bounds_events_without_claiming_a_complete_trace() -> None:
    capture = CaptureTraceSink(None)
    for _ in range(65):
        capture.emit(TraceEvent(request_id=uuid4(), kind=TraceKind.HTTP_COMPLETED))
    assert len(capture.frames) == 64
    assert capture.truncated is True


def test_trace_persistence_failure_does_not_change_research_answer(agent_auth) -> None:
    class BrokenStore:
        def save(self, *args):
            raise RuntimeError("private infrastructure details")

    app.state.research_trace_store = BrokenStore()
    try:
        response = TestClient(app).post("/api/v1/agent/query", headers=agent_auth.headers(), json={
            "query": "计算价格风险", "prices": [100, 101, 99, 102],
            "workspace_id": str(agent_auth.workspace_id),
        })
        assert response.status_code == 200
        assert response.headers["X-Trace-Status"] == "unavailable"
        assert "private infrastructure" not in response.text
    finally:
        del app.state.research_trace_store


def test_review_is_a_separate_stored_request_linked_by_thread(agent_auth) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ResearchTrace.__table__.create(engine)
    store = ResearchTraceStore(sessionmaker(bind=engine))
    app.state.research_trace_store = store
    app.state.research_checkpoints = ResearchCheckpointService(InMemorySaver())
    try:
        client = TestClient(app)
        created = client.post("/api/v1/agent/query", headers=agent_auth.headers(), json={
            "query": "计算价格风险", "prices": [100, 101, 99, 102],
            "workspace_id": str(agent_auth.workspace_id), "release_requested": True,
        })
        reviewed = client.post(f"/api/v1/agent/threads/{created.json()['thread_id']}/review",
                               headers=agent_auth.headers("reviewer"),
                               json={"choice": "rejected", "note": "PRIVATE_REVIEW_NOTE"})
        assert reviewed.status_code == 200
        assert reviewed.headers["X-Request-ID"] != created.headers["X-Request-ID"]
        saved = store.get(UUID(reviewed.headers["X-Request-ID"]))
        assert saved is not None and saved.owner_user_id == agent_auth.researcher_id
        assert saved.frames[0].event.kind == TraceKind.REVIEW_COMPLETED
        assert str(saved.frames[0].event.thread_id) == created.json()["thread_id"]
        assert "PRIVATE_REVIEW_NOTE" not in saved.model_dump_json()
    finally:
        del app.state.research_checkpoints
        del app.state.research_trace_store
        engine.dispose()
