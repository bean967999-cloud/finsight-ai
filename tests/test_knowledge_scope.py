"""Knowledge grants come from the database, not client-provided filters."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.api.routes.evidence import get_evidence_search
from finsight.domain.access_control import Action, ResourceScope, Role, evaluate_access
from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database import Base
from finsight.infrastructure.database.models import Document
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec
from finsight.services.knowledge_scope import KnowledgeScopeService

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


def test_database_grants_and_evidence_route_fail_closed() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    identity = IdentityService(factory)
    workspace_id = identity.create_workspace("Research Team")
    foreign_workspace_id = identity.create_workspace("Other Team")
    base_id = identity.create_knowledge_base(workspace_id, "Reports")
    foreign_base_id = identity.create_knowledge_base(foreign_workspace_id, "Reports")
    user_id = identity.provision("reader@example.com", PASSWORD)
    identity.assign_role(user_id, workspace_id, Role.RESEARCHER)
    with factory() as session, session.begin():
        document = Document(
            title="Report", document_type=DocumentType.ANNOUNCEMENT,
            object_key=f"reports/{uuid4()}.pdf", content_sha256="a" * 64,
            file_size_bytes=10,
        )
        session.add(document)
        session.flush()
        document_id = document.id
    identity.link_document(base_id, document_id)
    assert KnowledgeScopeService(factory).workspace_for(base_id) == workspace_id
    assert identity.resolve(user_id).memberships[0].knowledge_base_ids == ()

    previous_scope = app.state.knowledge_scope
    app.state.knowledge_scope = KnowledgeScopeService(factory)
    app.state.auth_service = AuthenticationService(identity, TokenCodec(SECRET))
    app.dependency_overrides[get_evidence_search] = lambda: object()
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {app.state.auth_service.login('reader@example.com', PASSWORD)}"}
        request = {"query": "营业收入", "knowledge_base_id": str(base_id)}
        assert client.post("/api/v1/evidence/search", json=request).status_code == 401
        assert client.post(
            "/api/v1/evidence/search", headers=headers, json=request
        ).status_code == 403
        identity.grant_knowledge_base(user_id, base_id)
        principal = identity.resolve(user_id)
        assert principal.memberships[0].knowledge_base_ids == (base_id,)
        assert evaluate_access(
            principal, Action.KNOWLEDGE_READ,
            ResourceScope(workspace_id=workspace_id, knowledge_base_id=base_id),
        ).allowed
        assert client.post(
            "/api/v1/evidence/search", headers=headers,
            json={**request, "knowledge_base_id": str(foreign_base_id)},
        ).status_code == 403
        assert client.post(
            "/api/v1/evidence/search", headers=headers,
            json={**request, "knowledge_base_id": str(uuid4())},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()
        del app.state.auth_service
        app.state.knowledge_scope = previous_scope
        engine.dispose()
