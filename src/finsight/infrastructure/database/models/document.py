from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.domain.document_data import DocumentType
from finsight.infrastructure.database.base import Base, TimestampMixin
from finsight.infrastructure.database.models.enums import enum_values

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.document_chunk import DocumentChunk
    from finsight.infrastructure.database.models.document_ingestion_job import DocumentIngestionJob
    from finsight.infrastructure.database.models.document_parse_job import DocumentParseJob


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint(
            "document_type NOT IN ('annual_report', 'semiannual_report', 'quarterly_report') "
            "OR (company_code IS NOT NULL AND report_year IS NOT NULL "
            "AND report_period_end IS NOT NULL)",
            name="report_metadata_required",
        ),
        Index("ix_documents_company_report_year", "company_code", "report_year"),
        Index("ix_documents_type_report_period", "document_type", "report_period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, native_enum=False, length=32, values_callable=enum_values),
        nullable=False,
    )
    company_code: Mapped[str | None] = mapped_column(String(32))
    security_symbol: Mapped[str | None] = mapped_column(String(50))
    report_year: Mapped[int | None]
    report_period_end: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(100), default="application/pdf", server_default="application/pdf", nullable=False
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")
    ingestion_jobs: Mapped[list["DocumentIngestionJob"]] = relationship(back_populates="document")
    parse_jobs: Mapped[list["DocumentParseJob"]] = relationship(back_populates="document")
