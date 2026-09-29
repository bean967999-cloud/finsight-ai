"""Day15 security acceptance across identity, resource scope, and audit failure."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.api.routes.evidence import get_evidence_search
from finsight.domain.access_control import Role
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AuditEvent, KnowledgeBaseGrant
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService
from finsight.services.operation_audit import OperationAuditService

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


def test_revocation_cross_workspace_and_failure_keep_traceable_audit() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    identity = IdentityService(sessions)
    workspace_id = identity.create_workspace("Day15 Research")
    other_workspace_id = identity.create_workspace("Day15 Other")
    base_id = identity.create_knowledge_base(workspace_id, "Private Reports")
    other_base_id = identity.create_knowledge_base(other_workspace_id, "Other Reports")
    user_id = identity.provision("day15@example.com", PASSWORD)
    identity.assign_role(user_id, workspace_id, Role.RESEARCHER)

    class BrokenEvidence:
        calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("upstream retrieval failed")

    broken = BrokenEvidence()
    previous_scope = app.state.knowledge_scope
    app.state.knowledge_scope = KnowledgeScopeService(sessions)
    app.state.auth_service = AuthenticationService(identity, TokenCodec(SECRET))
    app.state.audit_service = OperationAuditService(sessions)
    app.dependency_overrides[get_evidence_search] = lambda: broken
    try:
        client = TestClient(app)
        login = client.post("/api/v1/auth/login", json={
            "email": "day15@example.com", "password": PASSWORD,
        })
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        payload = {"query": "营业收入", "knowledge_base_id": str(base_id)}

        no_grant = client.post("/api/v1/evidence/search", headers=headers, json=payload)
        foreign = client.post("/api/v1/evidence/search", headers=headers, json={
            **payload, "knowledge_base_id": str(other_base_id),
        })
        unknown = client.post("/api/v1/evidence/search", headers=headers, json={
            **payload, "knowledge_base_id": str(uuid4()),
        })
        assert [no_grant.status_code, foreign.status_code, unknown.status_code] == [403, 403, 404]
        assert broken.calls == 0

        identity.grant_knowledge_base(user_id, base_id)
        upstream_failure = client.post("/api/v1/evidence/search", headers=headers, json=payload)
        assert upstream_failure.status_code == 500
        assert upstream_failure.json() == {"detail": "请求处理失败"}
        assert broken.calls == 1

        with sessions() as session, session.begin():
            session.execute(delete(KnowledgeBaseGrant).where(
                KnowledgeBaseGrant.user_id == user_id,
                KnowledgeBaseGrant.knowledge_base_id == base_id,
            ))
        revoked = client.post("/api/v1/evidence/search", headers=headers, json=payload)
        assert revoked.status_code == 403
        assert broken.calls == 1

        with sessions() as session:
            for response, outcome in (
                (no_grant, "denied"), (foreign, "denied"),
                (unknown, "failed"), (upstream_failure, "failed"),
                (revoked, "denied"),
            ):
                request_id = UUID(response.headers["X-Request-ID"])
                event = session.get(AuditEvent, request_id)
                assert event is not None
                assert event.outcome == outcome
                assert event.status_code == response.status_code
                assert event.actor_user_id == user_id
                assert event.route_pattern == "/api/v1/evidence/search"
            assert session.get(AuditEvent, UUID(login.headers["X-Request-ID"])) is not None
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_service
        del app.state.auth_service
        app.state.knowledge_scope = previous_scope
        engine.dispose()


def test_audit_finish_failure_returns_traceable_503() -> None:
    class FinishUnavailable:
        def __init__(self) -> None:
            self.started: list[UUID] = []

        def begin(self, request_id: UUID, **kwargs) -> None:
            self.started.append(request_id)

        def finish(self, request_id: UUID, **kwargs) -> None:
            raise OSError("audit update unavailable")

    audit = FinishUnavailable()
    app.state.audit_service = audit
    try:
        response = TestClient(app).post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "wrong",
        })
        assert response.status_code == 503
        assert response.json() == {"detail": "操作审计未能完成"}
        assert audit.started == [UUID(response.headers["X-Request-ID"])]
    finally:
        del app.state.audit_service


def test_audit_begin_failure_prevents_retrieval_invocation(agent_auth) -> None:
    class StartUnavailable:
        def begin(self, *args, **kwargs) -> None:
            raise OSError("audit unavailable")

    class CountingSearch:
        calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("should not be called")

    search = CountingSearch()
    app.state.audit_service = StartUnavailable()
    app.dependency_overrides[get_evidence_search] = lambda: search
    try:
        response = TestClient(app).post(
            "/api/v1/evidence/search", headers=agent_auth.headers(),
            json={"query": "营业收入", "knowledge_base_id": str(agent_auth.knowledge_base_id)},
        )
        assert response.status_code == 503
        assert UUID(response.headers["X-Request-ID"])
        assert search.calls == 0
    finally:
        app.dependency_overrides.clear()
        del app.state.audit_service
