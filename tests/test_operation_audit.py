"""Request IDs and sensitive-operation records never contain request secrets."""

from uuid import UUID

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AuditEvent
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.operation_audit import OperationAuditService, audit_target


def test_audit_target_uses_fixed_route_labels() -> None:
    assert audit_target("POST", "/api/v1/auth/login") == (
        "auth_login", "/api/v1/auth/login", None
    )
    assert audit_target("POST", "/api/v1/agent/threads/" + "a" * 36 + "/review") == (
        "review_decide", "/api/v1/agent/threads/{thread_id}/review", "a" * 36
    )
    assert audit_target("GET", "/api/v1/health") is None
    assert audit_target("POST", "/api/v1/auth/login?password=secret") is None


def test_login_audit_records_outcome_and_actor_without_password() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    identity = IdentityService(sessions)
    user_id = identity.provision("audit@example.com", "correct horse battery staple")
    app.state.auth_service = AuthenticationService(
        identity, TokenCodec("test-only-signing-secret-at-least-32-bytes")
    )
    app.state.audit_service = OperationAuditService(sessions)
    try:
        client = TestClient(app)
        ok = client.post("/api/v1/auth/login", json={
            "email": "audit@example.com", "password": "correct horse battery staple",
        })
        bad = client.post("/api/v1/auth/login", json={
            "email": "audit@example.com", "password": "wrong password",
        })
        assert ok.status_code == 200
        assert bad.status_code == 401
        assert UUID(ok.headers["X-Request-ID"]) != UUID(bad.headers["X-Request-ID"])
        assert UUID(client.get("/health").headers["X-Request-ID"])
        with sessions() as session:
            events = session.scalars(select(AuditEvent).order_by(AuditEvent.started_at)).all()
            assert len(events) == 2
            by_id = {str(event.request_id): event for event in events}
            success = by_id[ok.headers["X-Request-ID"]]
            denied = by_id[bad.headers["X-Request-ID"]]
            assert success.outcome == "succeeded" and success.actor_user_id == user_id
            assert denied.outcome == "denied" and denied.actor_user_id is None
            assert success.status_code == 200 and denied.status_code == 401
            assert success.finished_at is not None
            assert "password" not in repr(success.__dict__)
            assert "correct horse battery staple" not in repr(success.__dict__)
    finally:
        del app.state.audit_service
        del app.state.auth_service
        engine.dispose()


def test_sensitive_route_does_not_execute_when_audit_begin_fails() -> None:
    class UnavailableAudit:
        def begin(self, *args, **kwargs) -> None:
            raise OSError("database unavailable")

    app.state.audit_service = UnavailableAudit()
    try:
        response = TestClient(app).post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "secret",
        })
        assert response.status_code == 503
        assert UUID(response.headers["X-Request-ID"])
    finally:
        del app.state.audit_service


def test_review_audit_keeps_actor_and_workspace_scope(agent_auth) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    app.state.audit_service = OperationAuditService(sessions)
    app.state.research_checkpoints = ResearchCheckpointService(InMemorySaver())
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/agent/query", headers=agent_auth.headers(),
            json={
                "query": "计算价格波动率", "prices": [100, 102, 101, 105],
                "release_requested": True, "workspace_id": str(agent_auth.workspace_id),
            },
        )
        assert created.status_code == 200
        thread_id = created.json()["thread_id"]
        reviewed = client.post(
            f"/api/v1/agent/threads/{thread_id}/review",
            headers=agent_auth.headers("reviewer"), json={"choice": "confirmed"},
        )
        assert reviewed.status_code == 200
        with sessions() as session:
            submitted = session.get(AuditEvent, UUID(created.headers["X-Request-ID"]))
            decided = session.get(AuditEvent, UUID(reviewed.headers["X-Request-ID"]))
            assert submitted is not None and decided is not None
            assert submitted.actor_user_id == agent_auth.researcher_id
            assert decided.actor_user_id == agent_auth.reviewer_id
            assert submitted.workspace_id == agent_auth.workspace_id
            assert decided.workspace_id == agent_auth.workspace_id
            assert decided.action == "review_decide"
            assert decided.target_id == thread_id
            assert decided.outcome == "succeeded"
    finally:
        del app.state.audit_service
        del app.state.research_checkpoints
        engine.dispose()
