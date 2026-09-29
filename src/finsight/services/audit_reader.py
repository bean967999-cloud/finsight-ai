"""Bounded workspace-scoped metadata reads; unscoped records are never included."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from finsight.infrastructure.database.models.audit_event import AuditEvent


class AuditRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    action: str
    method: str
    route_pattern: str
    actor_user_id: UUID | None
    workspace_id: UUID
    outcome: str
    status_code: int | None
    started_at: datetime
    finished_at: datetime | None


class AuditPage(BaseModel):
    workspace_id: UUID
    records: tuple[AuditRecord, ...]
    offset: int
    limit: int
    has_more: bool


class AuditReader:
    def __init__(self, sessions: Callable[[], Session]) -> None:
        self._sessions = sessions

    def read(self, workspace_id: UUID, *, offset: int, limit: int) -> AuditPage:
        if not 0 <= offset <= 10000 or not 1 <= limit <= 50:
            raise ValueError("pagination is out of bounds")
        statement = (
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.started_at.desc(), AuditEvent.request_id.desc())
            .offset(offset).limit(limit + 1)
        )
        with self._sessions() as session:
            rows = session.scalars(statement).all()
            return AuditPage(
                workspace_id=workspace_id,
                records=tuple(AuditRecord.model_validate(item) for item in rows[:limit]),
                offset=offset, limit=limit, has_more=len(rows) > limit,
            )
