"""Pure authorization contract; HTTP identity and persistence are separate layers."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class Role(StrEnum):
    VIEWER = "viewer"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    WORKSPACE_ADMIN = "workspace_admin"


class Action(StrEnum):
    RESEARCH_READ = "research_read"
    RESEARCH_SUBMIT = "research_submit"
    RELEASE_REQUEST = "release_request"
    REVIEW_READ = "review_read"
    REVIEW_DECIDE = "review_decide"
    KNOWLEDGE_READ = "knowledge_read"
    KNOWLEDGE_MANAGE = "knowledge_manage"
    MEMBERSHIP_MANAGE = "membership_manage"


ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.RESEARCH_READ, Action.KNOWLEDGE_READ}),
    Role.RESEARCHER: frozenset({
        Action.RESEARCH_READ,
        Action.RESEARCH_SUBMIT,
        Action.RELEASE_REQUEST,
        Action.KNOWLEDGE_READ,
    }),
    Role.REVIEWER: frozenset({
        Action.RESEARCH_READ,
        Action.REVIEW_READ,
        Action.REVIEW_DECIDE,
        Action.KNOWLEDGE_READ,
    }),
    Role.WORKSPACE_ADMIN: frozenset({
        Action.RESEARCH_READ,
        Action.RESEARCH_SUBMIT,
        Action.RELEASE_REQUEST,
        Action.REVIEW_READ,
        Action.KNOWLEDGE_READ,
        Action.KNOWLEDGE_MANAGE,
        Action.MEMBERSHIP_MANAGE,
    }),
}


class WorkspaceMembership(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    role: Role
    knowledge_base_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def unique_knowledge_bases(self) -> WorkspaceMembership:
        if len(self.knowledge_base_ids) != len(set(self.knowledge_base_ids)):
            raise ValueError("knowledge base grants must be unique")
        return self


class Principal(BaseModel):
    """Resolved server-side identity, never a client-selected role or workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    active: bool = True
    memberships: tuple[WorkspaceMembership, ...] = ()

    @model_validator(mode="after")
    def unique_workspaces(self) -> Principal:
        ids = [membership.workspace_id for membership in self.memberships]
        if len(ids) != len(set(ids)):
            raise ValueError("one membership per workspace is required")
        return self


class ResourceScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    knowledge_base_id: UUID | None = None
    owner_user_id: UUID | None = None


class AccessReason(StrEnum):
    ALLOWED = "allowed"
    INACTIVE_USER = "inactive_user"
    WORKSPACE_NOT_GRANTED = "workspace_not_granted"
    ACTION_NOT_GRANTED = "action_not_granted"
    KNOWLEDGE_BASE_REQUIRED = "knowledge_base_required"
    KNOWLEDGE_BASE_NOT_GRANTED = "knowledge_base_not_granted"
    REVIEW_OWNER_REQUIRED = "review_owner_required"
    SELF_REVIEW_FORBIDDEN = "self_review_forbidden"


class AccessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: AccessReason


def evaluate_access(principal: Principal, action: Action, resource: ResourceScope) -> AccessDecision:
    """Fail closed: both action permission and resource scope must pass."""
    if not principal.active:
        return AccessDecision(allowed=False, reason=AccessReason.INACTIVE_USER)
    membership = next(
        (item for item in principal.memberships if item.workspace_id == resource.workspace_id),
        None,
    )
    if membership is None:
        return AccessDecision(allowed=False, reason=AccessReason.WORKSPACE_NOT_GRANTED)
    if action not in ROLE_ACTIONS[membership.role]:
        return AccessDecision(allowed=False, reason=AccessReason.ACTION_NOT_GRANTED)
    if action in {Action.KNOWLEDGE_READ, Action.KNOWLEDGE_MANAGE} and resource.knowledge_base_id is None:
        return AccessDecision(allowed=False, reason=AccessReason.KNOWLEDGE_BASE_REQUIRED)
    if (
        resource.knowledge_base_id is not None
        and membership.role != Role.WORKSPACE_ADMIN
        and resource.knowledge_base_id not in membership.knowledge_base_ids
    ):
        return AccessDecision(allowed=False, reason=AccessReason.KNOWLEDGE_BASE_NOT_GRANTED)
    if action == Action.REVIEW_DECIDE:
        if resource.owner_user_id is None:
            return AccessDecision(allowed=False, reason=AccessReason.REVIEW_OWNER_REQUIRED)
        if resource.owner_user_id == principal.user_id:
            return AccessDecision(allowed=False, reason=AccessReason.SELF_REVIEW_FORBIDDEN)
    return AccessDecision(allowed=True, reason=AccessReason.ALLOWED)
