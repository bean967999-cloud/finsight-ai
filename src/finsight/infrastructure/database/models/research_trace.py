"""Scoped, bounded diagnostic snapshots; distinct from operation audit."""

from uuid import UUID

from sqlalchemy import JSON, Boolean, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from finsight.infrastructure.database.base import Base


class ResearchTrace(Base):
    __tablename__ = "research_traces"
    __table_args__ = (Index("ix_research_traces_workspace_owner", "workspace_id", "owner_user_id"),)

    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    knowledge_base_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    frames: Mapped[list] = mapped_column(JSON, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
