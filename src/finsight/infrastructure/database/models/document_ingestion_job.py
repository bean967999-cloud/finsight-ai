from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.domain.document_data import DocumentIngestionStatus
from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.document import Document


class DocumentIngestionJob(TimestampMixin, Base):
    __tablename__ = "document_ingestion_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        Index("ix_document_ingestion_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT")
    )
    status: Mapped[DocumentIngestionStatus] = mapped_column(
        Enum(
            DocumentIngestionStatus,
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=DocumentIngestionStatus.PENDING,
        server_default=DocumentIngestionStatus.PENDING.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped["Document | None"] = relationship(back_populates="ingestion_jobs")
