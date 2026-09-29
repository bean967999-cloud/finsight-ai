"""Workspace-admin-only audit reads; no account or role mutations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from finsight.api.routes.auth import get_current_principal
from finsight.domain.access_control import Role
from finsight.infrastructure.database.session import SessionFactory
from finsight.services.audit_reader import AuditPage, AuditReader

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def get_audit_reader() -> AuditReader:
    return AuditReader(SessionFactory)


@router.get("/workspaces/{workspace_id}/audit", response_model=AuditPage)
def read_audit(
    workspace_id: UUID,
    request: Request,
    reader: Annotated[AuditReader, Depends(get_audit_reader)],
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AuditPage:
    principal = get_current_principal(request)
    if not any(
        item.workspace_id == workspace_id and item.role == Role.WORKSPACE_ADMIN
        for item in principal.memberships
    ):
        raise HTTPException(403, "无权读取该工作空间的审计记录")
    request.state.audit_workspace_id = workspace_id
    try:
        return reader.read(workspace_id, offset=offset, limit=limit)
    except SQLAlchemyError as error:
        raise HTTPException(503, "审计查询暂时不可用") from error
