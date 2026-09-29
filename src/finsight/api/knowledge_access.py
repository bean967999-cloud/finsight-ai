"""Resolve knowledge-base ownership before applying the role/scope policy."""

from uuid import UUID

from fastapi import HTTPException, Request

from finsight.domain.access_control import Action, Principal, ResourceScope, evaluate_access


def require_knowledge_access(
    request: Request, principal: Principal, knowledge_base_id: UUID, action: Action
) -> UUID:
    service = getattr(request.app.state, "knowledge_scope", None)
    if service is None:
        raise HTTPException(503, "知识库归属服务不可用")
    workspace_id = service.workspace_for(knowledge_base_id)
    if workspace_id is None:
        raise HTTPException(404, "知识库不存在")
    request.state.audit_workspace_id = workspace_id
    request.state.audit_knowledge_base_id = knowledge_base_id
    scope = ResourceScope(workspace_id=workspace_id, knowledge_base_id=knowledge_base_id)
    if not evaluate_access(principal, action, scope).allowed:
        raise HTTPException(403, "无权访问此知识库")
    return workspace_id
