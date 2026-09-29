"""Workspace membership is the durable source of a user's role."""

from uuid import UUID, uuid4

from sqlalchemy import Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from finsight.domain.access_control import Role
from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import enum_values


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_memberships"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=20, values_callable=enum_values), nullable=False
    )
