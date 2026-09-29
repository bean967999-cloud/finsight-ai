"""Persistent orchestration job; PostgreSQL is the source of task truth."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from finsight.domain.async_job import AsyncJobStatus
from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import enum_values


class AsyncJob(TimestampMixin, Base):
    __tablename__ = "async_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts_range"),
        Index("ix_async_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_base_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    task_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[AsyncJobStatus] = mapped_column(
        Enum(AsyncJobStatus, native_enum=False, length=16, values_callable=enum_values),
        default=AsyncJobStatus.PENDING,
        server_default=AsyncJobStatus.PENDING.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3", nullable=False
    )
    result_ref: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(100))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
