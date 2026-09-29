from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import (
    ImportJobStatus,
    ImportJobType,
    enum_values,
)

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.data_source import DataSource


class ImportJob(TimestampMixin, Base):
    __tablename__ = "import_jobs"
    __table_args__ = (Index("ix_import_jobs_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    job_type: Mapped[ImportJobType] = mapped_column(
        Enum(ImportJobType, native_enum=False, length=32, values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[ImportJobStatus] = mapped_column(
        Enum(
            ImportJobStatus,
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=ImportJobStatus.PENDING,
        server_default=ImportJobStatus.PENDING.value,
        nullable=False,
    )
    request_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)

    data_source: Mapped["DataSource"] = relationship(back_populates="import_jobs")
