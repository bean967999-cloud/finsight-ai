"""Independent lifecycle and artifact pointers for one PDF parse attempt."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.domain.document_data import DocumentParseStatus
from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.document import Document


class DocumentParseJob(TimestampMixin, Base):
    __tablename__ = "document_parse_jobs"
    __table_args__ = (
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
        Index("ix_document_parse_jobs_document_created", "document_id", "created_at"),
        Index("ix_document_parse_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[DocumentParseStatus] = mapped_column(
        Enum(DocumentParseStatus, native_enum=False, length=16, values_callable=enum_values),
        nullable=False,
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36))
    parser_name: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str | None] = mapped_column(String(50))
    page_count: Mapped[int | None]
    markdown_key: Mapped[str | None] = mapped_column(String(500))
    content_list_key: Mapped[str | None] = mapped_column(String(500))
    middle_json_key: Mapped[str | None] = mapped_column(String(500))
    parsed_document_key: Mapped[str | None] = mapped_column(String(500))
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped["Document"] = relationship(back_populates="parse_jobs")
