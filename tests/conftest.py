"""Explicit identity fixture for legacy graph HTTP tests."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.main import app
from finsight.services.identity import InvalidCredentials


@dataclass(frozen=True)
class AgentAuthFixture:
    workspace_id: UUID
    knowledge_base_id: UUID
    researcher_id: UUID
    reviewer_id: UUID

    @staticmethod
    def headers(role: str = "researcher") -> dict[str, str]:
        return {"Authorization": f"Bearer test-{role}-token"}


@pytest.fixture
def agent_auth():
    workspace_id = uuid4()
    knowledge_base_id = uuid4()
    researcher_id = uuid4()
    reviewer_id = uuid4()
    fixture = AgentAuthFixture(workspace_id, knowledge_base_id, researcher_id, reviewer_id)

    class AuthStub:
        @staticmethod
        def resolve(token: str) -> Principal:
            mapping = {
                "test-researcher-token": (researcher_id, Role.RESEARCHER),
                "test-reviewer-token": (reviewer_id, Role.REVIEWER),
            }
            if token not in mapping:
                raise InvalidCredentials("invalid credentials")
            user_id, role = mapping[token]
            return Principal(
                user_id=user_id,
                memberships=(WorkspaceMembership(
                    workspace_id=workspace_id, role=role,
                    knowledge_base_ids=(knowledge_base_id,),
                ),),
            )

    class ScopeStub:
        @staticmethod
        def workspace_for(candidate: UUID) -> UUID | None:
            return workspace_id if candidate == knowledge_base_id else None

    app.state.auth_service = AuthStub()
    previous_scope = app.state.knowledge_scope
    app.state.knowledge_scope = ScopeStub()
    try:
        yield fixture
    finally:
        del app.state.auth_service
        app.state.knowledge_scope = previous_scope
