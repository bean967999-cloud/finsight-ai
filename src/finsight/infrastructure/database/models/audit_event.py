"""Minimal, durable metadata for security-relevant HTTP operations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from finsight.infrastructure.database.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    route_pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128))
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
