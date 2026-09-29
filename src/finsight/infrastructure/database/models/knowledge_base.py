"""Workspace-owned knowledge bases, user grants, and document associations."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from finsight.infrastructure.database.base import Base, TimestampMixin


class KnowledgeBase(TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class KnowledgeBaseGrant(Base):
    __tablename__ = "knowledge_base_grants"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )


class KnowledgeBaseDocument(Base):
    __tablename__ = "knowledge_base_documents"

    knowledge_base_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
