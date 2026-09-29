"""Day15 Step1: role permissions and resource scopes are explicit and fail closed."""

from uuid import uuid4

import pytest

from finsight.domain.access_control import (
    ROLE_ACTIONS,
    AccessReason,
    Action,
    Principal,
    ResourceScope,
    Role,
    WorkspaceMembership,
    evaluate_access,
)

USER_ID = uuid4()
OTHER_USER_ID = uuid4()
WORKSPACE_ID = uuid4()
OTHER_WORKSPACE_ID = uuid4()
KNOWLEDGE_BASE_ID = uuid4()
OTHER_KNOWLEDGE_BASE_ID = uuid4()


def principal(role: Role, *, active: bool = True) -> Principal:
    return Principal(
        user_id=USER_ID,
        active=active,
        memberships=(WorkspaceMembership(
            workspace_id=WORKSPACE_ID,
            role=role,
            knowledge_base_ids=(KNOWLEDGE_BASE_ID,),
        ),),
    )


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("action", list(Action))
def test_role_matrix_is_explicit(role: Role, action: Action) -> None:
    scope = ResourceScope(
        workspace_id=WORKSPACE_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        owner_user_id=OTHER_USER_ID,
    )
    result = evaluate_access(principal(role), action, scope)
    assert result.allowed is (action in ROLE_ACTIONS[role])


def test_workspace_and_knowledge_base_must_both_match() -> None:
    researcher = principal(Role.RESEARCHER)
    foreign_workspace = ResourceScope(
        workspace_id=OTHER_WORKSPACE_ID, knowledge_base_id=KNOWLEDGE_BASE_ID
    )
    assert evaluate_access(researcher, Action.RESEARCH_READ, foreign_workspace).reason == (
        AccessReason.WORKSPACE_NOT_GRANTED
    )
    foreign_knowledge = ResourceScope(
        workspace_id=WORKSPACE_ID, knowledge_base_id=OTHER_KNOWLEDGE_BASE_ID
    )
    assert evaluate_access(researcher, Action.RESEARCH_READ, foreign_knowledge).reason == (
        AccessReason.KNOWLEDGE_BASE_NOT_GRANTED
    )
    assert evaluate_access(principal(Role.WORKSPACE_ADMIN), Action.KNOWLEDGE_READ, foreign_knowledge).allowed


def test_knowledge_operation_needs_a_specific_knowledge_base() -> None:
    scope = ResourceScope(workspace_id=WORKSPACE_ID)
    result = evaluate_access(principal(Role.RESEARCHER), Action.KNOWLEDGE_READ, scope)
    assert result.reason == AccessReason.KNOWLEDGE_BASE_REQUIRED


def test_reviewer_cannot_approve_own_or_ownerless_request() -> None:
    reviewer = principal(Role.REVIEWER)
    own = ResourceScope(workspace_id=WORKSPACE_ID, owner_user_id=USER_ID)
    missing_owner = ResourceScope(workspace_id=WORKSPACE_ID)
    other = ResourceScope(workspace_id=WORKSPACE_ID, owner_user_id=OTHER_USER_ID)
    assert evaluate_access(reviewer, Action.REVIEW_DECIDE, own).reason == (
        AccessReason.SELF_REVIEW_FORBIDDEN
    )
    assert evaluate_access(reviewer, Action.REVIEW_DECIDE, missing_owner).reason == (
        AccessReason.REVIEW_OWNER_REQUIRED
    )
    assert evaluate_access(reviewer, Action.REVIEW_DECIDE, other).allowed
    assert not evaluate_access(principal(Role.WORKSPACE_ADMIN), Action.REVIEW_DECIDE, other).allowed


def test_inactive_user_is_denied_and_membership_contract_rejects_duplicates() -> None:
    scope = ResourceScope(workspace_id=WORKSPACE_ID)
    assert evaluate_access(principal(Role.RESEARCHER, active=False), Action.RESEARCH_SUBMIT, scope).reason == (
        AccessReason.INACTIVE_USER
    )
    membership = WorkspaceMembership(workspace_id=WORKSPACE_ID, role=Role.VIEWER)
    with pytest.raises(ValueError, match="one membership"):
        Principal(user_id=USER_ID, memberships=(membership, membership))
    with pytest.raises(ValueError, match="knowledge base grants"):
        WorkspaceMembership(
            workspace_id=WORKSPACE_ID,
            role=Role.RESEARCHER,
            knowledge_base_ids=(KNOWLEDGE_BASE_ID, KNOWLEDGE_BASE_ID),
        )


def test_identity_contract_json_round_trip_keeps_uuid_scopes() -> None:
    resolved = principal(Role.REVIEWER)
    assert Principal.model_validate_json(resolved.model_dump_json()) == resolved
