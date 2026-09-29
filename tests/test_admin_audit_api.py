"""Audit reads enforce exact workspace scope and bounded pagination."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.api.routes.admin import get_audit_reader
from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.infrastructure.database.models.audit_event import AuditEvent
from finsight.main import app
from finsight.services.audit_reader import AuditReader
from finsight.services.identity import InvalidCredentials


def test_admin_audit_is_scoped_paginated_and_metadata_only() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    AuditEvent.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    workspace, other = uuid4(), uuid4()
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        for index, scope in enumerate((workspace, workspace, other, None)):
            session.add(AuditEvent(
                request_id=uuid4(), workspace_id=scope, action="research_submit",
                method="POST", route_pattern="/api/v1/agent/query", outcome="succeeded",
                status_code=200, started_at=now + timedelta(seconds=index),
            ))

    class AuthStub:
        @staticmethod
        def resolve(token: str) -> Principal:
            if token not in {"admin", "viewer"}:
                raise InvalidCredentials("invalid token")
            return Principal(user_id=uuid4(), memberships=(WorkspaceMembership(
                workspace_id=workspace,
                role=Role.WORKSPACE_ADMIN if token == "admin" else Role.VIEWER,
            ),))

    previous = getattr(app.state, "auth_service", None)
    app.state.auth_service = AuthStub()
    app.dependency_overrides[get_audit_reader] = lambda: AuditReader(sessions)
    try:
        client = TestClient(app)
        path = f"/api/v1/admin/workspaces/{workspace}/audit"
        headers = {"Authorization": "Bearer admin"}
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer viewer"}).status_code == 403
        assert client.get(f"/api/v1/admin/workspaces/{other}/audit", headers=headers).status_code == 403
        first = client.get(path, params={"limit": 1}, headers=headers)
        assert first.status_code == 200
        assert first.json()["has_more"] is True
        assert all(item["workspace_id"] == str(workspace) for item in first.json()["records"])
        second = client.get(path, params={"limit": 1, "offset": 1}, headers=headers).json()
        assert second["has_more"] is False
        assert second["records"][0]["request_id"] != first.json()["records"][0]["request_id"]
        assert client.get(path, params={"limit": 51}, headers=headers).status_code == 422
        assert client.get(path, params={"offset": -1}, headers=headers).status_code == 422
        assert "target_id" not in second["records"][0]
    finally:
        app.dependency_overrides.pop(get_audit_reader, None)
        if previous is None:
            del app.state.auth_service
        else:
            app.state.auth_service = previous
        engine.dispose()
