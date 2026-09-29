"""Persisted local identity; role memberships are added separately."""

from uuid import UUID, uuid4

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from finsight.infrastructure.database.base import Base, TimestampMixin


class UserAccount(TimestampMixin, Base):
    __tablename__ = "user_accounts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
