from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finsight.infrastructure.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from finsight.infrastructure.database.models.document import Document


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_version", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("chunk_version >= 1", name="chunk_version_positive"),
        CheckConstraint("page_start > 0", name="page_start_positive"),
        CheckConstraint("page_end >= page_start", name="page_range_valid"),
        Index("ix_document_chunks_document_page", "document_id", "page_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    parse_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_parse_jobs.id", ondelete="RESTRICT")
    )
    kind: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(Text)
    section_path: Mapped[list[str] | None] = mapped_column(JSON)
    source_blocks: Mapped[list[dict[str, int]] | None] = mapped_column(JSON)
    table_format: Mapped[str | None] = mapped_column(String(16))
    asset_path: Mapped[str | None] = mapped_column(String(500))
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(500))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(100), unique=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")
