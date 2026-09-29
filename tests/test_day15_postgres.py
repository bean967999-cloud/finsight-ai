"""Opt-in Day15 HTTP acceptance backed by an isolated PostgreSQL schema."""

import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from finsight.api.routes.evidence import get_evidence_search
from finsight.core.config import get_settings
from finsight.domain.access_control import Role
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import AuditEvent
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService
from finsight.services.operation_audit import OperationAuditService

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_PG_INTEGRATION") != "1",
    reason="Set FINSIGHT_PG_INTEGRATION=1 for isolated PostgreSQL authorization acceptance",
)


def test_postgres_identity_scope_and_audit_http_round_trip() -> None:
    schema = f"finsight_day15_{uuid4().hex[:12]}"
    admin = create_engine(get_settings().database_url)
    test_engine = None
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        test_engine = create_engine(
            get_settings().database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        Base.metadata.create_all(test_engine)
        sessions = sessionmaker(test_engine, class_=Session, expire_on_commit=False)
        identity = IdentityService(sessions)
        workspace_id = identity.create_workspace("PG Research")
        base_id = identity.create_knowledge_base(workspace_id, "PG Reports")
        user_id = identity.provision("pg-day15@example.com", "correct horse battery staple")
        identity.assign_role(user_id, workspace_id, Role.RESEARCHER)

        class NoSearch:
            def search(self, *args, **kwargs):
                raise AssertionError("denied request must not reach retrieval")

        previous_scope = app.state.knowledge_scope
        app.state.auth_service = AuthenticationService(
            identity, TokenCodec("test-only-signing-secret-at-least-32-bytes")
        )
        app.state.knowledge_scope = KnowledgeScopeService(sessions)
        app.state.audit_service = OperationAuditService(sessions)
        app.dependency_overrides[get_evidence_search] = lambda: NoSearch()
        try:
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={
                "email": "pg-day15@example.com", "password": "correct horse battery staple",
            })
            assert login.status_code == 200
            denied = client.post(
                "/api/v1/evidence/search",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                json={"query": "营业收入", "knowledge_base_id": str(base_id)},
            )
            assert denied.status_code == 403
            with sessions() as session:
                event = session.get(AuditEvent, UUID(denied.headers["X-Request-ID"]))
                assert event is not None
                assert event.actor_user_id == user_id
                assert event.workspace_id == workspace_id
                assert event.knowledge_base_id == base_id
                assert event.outcome == "denied"
                assert event.status_code == 403
        finally:
            app.dependency_overrides.clear()
            del app.state.audit_service
            del app.state.auth_service
            app.state.knowledge_scope = previous_scope
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
