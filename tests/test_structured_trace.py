"""Day16 Step4: request-linked local traces contain metadata, never raw inputs."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.api.routes.evidence import get_evidence_search
from finsight.main import app
from finsight.services.structured_trace import TraceEvent, TraceKind


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


def test_research_trace_correlates_plan_tool_and_http_without_raw_financial_input(agent_auth) -> None:
    sink = MemorySink()
    previous = app.state.trace_sink
    app.state.trace_sink = sink
    try:
        response = TestClient(app).post(
            "/api/v1/agent/query", headers=agent_auth.headers(),
            json={
                "query": "计算价格波动率 PRIVATE_QUERY_MARKER",
                "prices": [123456.789, 123460.0, 123450.0, 123470.0],
                "workspace_id": str(agent_auth.workspace_id),
            },
        )
        assert response.status_code == 200
        request_id = UUID(response.headers["X-Request-ID"])
        kinds = [event.kind for event in sink.events]
        assert TraceKind.RESEARCH_PLAN in kinds
        assert TraceKind.TOOL_COMPLETED in kinds
        assert TraceKind.RESEARCH_COMPLETED in kinds
        assert kinds[-1] == TraceKind.HTTP_COMPLETED
        assert {event.request_id for event in sink.events} == {request_id}
        tool = next(event for event in sink.events if event.kind == TraceKind.TOOL_COMPLETED)
        assert tool.tool == "risk_calculation"
        assert tool.tool_status == "succeeded"
        assert tool.duration_ms is not None and tool.duration_ms >= 0
        serialized = " ".join(item.model_dump_json() for item in sink.events)
        assert "PRIVATE_QUERY_MARKER" not in serialized
        assert "123456.789" not in serialized
        assert "test-researcher-token" not in serialized
    finally:
        app.state.trace_sink = previous


def test_denied_and_unhandled_failure_keep_only_safe_http_event(agent_auth) -> None:
    class BrokenSearch:
        def search(self, *args, **kwargs):
            raise RuntimeError("private document content should not reach logs")

    sink = MemorySink()
    previous = app.state.trace_sink
    app.state.trace_sink = sink
    app.dependency_overrides[get_evidence_search] = lambda: BrokenSearch()
    try:
        client = TestClient(app)
        payload = {
            "query": "PRIVATE_EVIDENCE_MARKER",
            "knowledge_base_id": str(agent_auth.knowledge_base_id),
        }
        denied = client.post("/api/v1/evidence/search", json=payload)
        failed = client.post(
            "/api/v1/evidence/search", headers=agent_auth.headers(), json=payload
        )
        assert denied.status_code == 401 and failed.status_code == 500
        events = [event for event in sink.events if event.kind == TraceKind.HTTP_COMPLETED]
        assert [event.status_code for event in events] == [401, 500]
        assert [event.request_id for event in events] == [
            UUID(denied.headers["X-Request-ID"]), UUID(failed.headers["X-Request-ID"])
        ]
        serialized = " ".join(item.model_dump_json() for item in sink.events)
        assert "PRIVATE_EVIDENCE_MARKER" not in serialized
        assert "private document content" not in serialized
    finally:
        app.dependency_overrides.clear()
        app.state.trace_sink = previous


def test_review_trace_links_later_request_by_thread_without_note(agent_auth) -> None:
    sink = MemorySink()
    previous = app.state.trace_sink
    app.state.trace_sink = sink
    app.state.research_checkpoints = ResearchCheckpointService(InMemorySaver())
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/agent/query", headers=agent_auth.headers(),
            json={
                "query": "计算价格波动率", "prices": [100, 102, 101, 105],
                "workspace_id": str(agent_auth.workspace_id), "release_requested": True,
            },
        )
        assert created.status_code == 200
        thread_id = UUID(created.json()["thread_id"])
        reviewed = client.post(
            f"/api/v1/agent/threads/{thread_id}/review",
            headers=agent_auth.headers("reviewer"),
            json={"choice": "rejected", "note": "PRIVATE_REVIEW_NOTE"},
        )
        assert reviewed.status_code == 200
        review_event = next(
            item for item in sink.events if item.kind == TraceKind.REVIEW_COMPLETED
        )
        assert review_event.thread_id == thread_id
        assert review_event.review_choice == "rejected"
        assert review_event.request_id == UUID(reviewed.headers["X-Request-ID"])
        assert "PRIVATE_REVIEW_NOTE" not in review_event.model_dump_json()
    finally:
        del app.state.research_checkpoints
        app.state.trace_sink = previous


def test_event_contract_rejects_raw_content_and_nonfinite_duration() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(request_id=UUID(int=1), kind=TraceKind.HTTP_COMPLETED, raw_query="secret")
    with pytest.raises(ValidationError):
        TraceEvent(
            request_id=UUID(int=1), kind=TraceKind.HTTP_COMPLETED,
            duration_ms=float("nan"),
        )
