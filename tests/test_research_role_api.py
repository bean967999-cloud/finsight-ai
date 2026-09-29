"""Real database memberships control research and review HTTP actions."""

from uuid import uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finsight.agents.checkpoints import ResearchCheckpointService
from finsight.domain.access_control import Role
from finsight.infrastructure.database import Base
from finsight.main import app
from finsight.services.identity import AuthenticationService, IdentityService, TokenCodec

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


def test_role_matrix_is_enforced_on_research_and_review_endpoints() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    identity = IdentityService(sessionmaker(bind=engine, expire_on_commit=False))
    workspace_id = identity.create_workspace("Research Team")
    other_workspace_id = identity.create_workspace("Other Team")
    users = {}
    for role in Role:
        email = f"{role.value}@example.com"
        user_id = identity.provision(email, PASSWORD)
        identity.assign_role(user_id, workspace_id, role)
        users[role] = (email, user_id)
    other_reviewer = identity.provision("other-reviewer@example.com", PASSWORD)
    identity.assign_role(other_reviewer, other_workspace_id, Role.REVIEWER)
    app.state.auth_service = AuthenticationService(identity, TokenCodec(SECRET))
    service = ResearchCheckpointService(InMemorySaver())
    app.state.research_checkpoints = service
    try:
        client = TestClient(app)

        def headers(email: str) -> dict[str, str]:
            response = client.post(
                "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert response.status_code == 200
            return {"Authorization": f"Bearer {response.json()['access_token']}"}

        researcher = headers(users[Role.RESEARCHER][0])
        reviewer = headers(users[Role.REVIEWER][0])
        viewer = headers(users[Role.VIEWER][0])
        admin = headers(users[Role.WORKSPACE_ADMIN][0])
        foreign_reviewer = headers("other-reviewer@example.com")
        question = {
            "query": "计算价格波动率",
            "prices": [100, 102, 101, 105],
            "workspace_id": str(workspace_id),
            "release_requested": True,
        }
        assert client.post("/api/v1/agent/query", json=question).status_code == 401
        assert client.post("/api/v1/agent/query", headers=viewer, json=question).status_code == 403
        assert client.post("/api/v1/agent/query", headers=reviewer, json=question).status_code == 403
        assert client.post(
            "/api/v1/agent/query", headers=researcher,
            json={**question, "workspace_id": str(other_workspace_id)},
        ).status_code == 403
        assert client.post(
            "/api/v1/agent/query", headers=researcher,
            json={**question, "owner_user_id": str(users[Role.REVIEWER][1])},
        ).status_code == 422
        created = client.post("/api/v1/agent/query", headers=researcher, json=question)
        assert created.status_code == 200
        thread_id = created.json()["thread_id"]
        saved = service.get(thread_id)
        assert saved is not None
        assert saved.workspace_id == workspace_id
        assert saved.owner_user_id == users[Role.RESEARCHER][1]
        path = f"/api/v1/agent/threads/{thread_id}"
        assert client.get(path, headers=researcher).status_code == 403
        assert client.get(path, headers=foreign_reviewer).status_code == 403
        assert client.get(path, headers=reviewer).status_code == 200
        assert client.get(path, headers=admin).status_code == 200
        assert client.post(
            f"{path}/review", headers=admin, json={"choice": "confirmed"}
        ).status_code == 403
        completed = client.post(
            f"{path}/review", headers=reviewer, json={"choice": "confirmed"}
        )
        assert completed.status_code == 200
        assert completed.json()["answer_status"] == "insufficient_evidence"
        assert client.post(
            f"{path}/review", headers=reviewer, json={"choice": "confirmed"}
        ).status_code == 409

        # Membership changes are read from the database, not stale token claims.
        identity.assign_role(users[Role.RESEARCHER][1], workspace_id, Role.VIEWER)
        assert client.post("/api/v1/agent/query", headers=researcher, json=question).status_code == 403
    finally:
        del app.state.research_checkpoints
        del app.state.auth_service
        engine.dispose()


def test_review_rejects_self_review_and_legacy_unscoped_threads(agent_auth) -> None:
    service = ResearchCheckpointService(InMemorySaver())
    app.state.research_checkpoints = service
    try:
        client = TestClient(app)
        self_owned = service.start({
            "query": "计算价格波动率", "prices": [100, 102, 101, 105],
            "release_requested": True,
            "workspace_id": str(agent_auth.workspace_id),
            "owner_user_id": str(agent_auth.reviewer_id),
        })
        legacy = service.start({
            "query": "计算价格波动率", "prices": [100, 102, 101, 105],
            "release_requested": True,
        })
        reviewer = agent_auth.headers("reviewer")
        assert client.post(
            f"/api/v1/agent/threads/{self_owned.thread_id}/review",
            headers=reviewer, json={"choice": "confirmed"},
        ).status_code == 403
        assert client.get(
            f"/api/v1/agent/threads/{legacy.thread_id}", headers=reviewer
        ).status_code == 403
        assert client.post(
            f"/api/v1/agent/threads/{legacy.thread_id}/review",
            headers=reviewer, json={"choice": "confirmed"},
        ).status_code == 403
        assert client.get(
            f"/api/v1/agent/threads/{uuid4()}", headers=reviewer
        ).status_code == 404
    finally:
        del app.state.research_checkpoints
