"""Add document, chunk metadata, and document ingestion job tables.

Revision ID: 20260921_0002
Revises: 20260915_0001
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0002"
down_revision: str | None = "20260915_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                "annual_report", "semiannual_report", "quarterly_report",
                "announcement", "regulatory_policy",
                name="documenttype", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("company_code", sa.String(length=32), nullable=True),
        sa.Column("security_symbol", sa.String(length=50), nullable=True),
        sa.Column("report_year", sa.Integer(), nullable=True),
        sa.Column("report_period_end", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "mime_type", sa.String(length=100),
            server_default="application/pdf", nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "file_size_bytes > 0", name=op.f("ck_documents_file_size_positive")
        ),
        sa.CheckConstraint(
            "document_type NOT IN ('annual_report', 'semiannual_report', 'quarterly_report') "
            "OR (company_code IS NOT NULL AND report_year IS NOT NULL "
            "AND report_period_end IS NOT NULL)",
            name=op.f("ck_documents_report_metadata_required"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("object_key", name=op.f("uq_documents_object_key")),
        sa.UniqueConstraint("content_sha256", name=op.f("uq_documents_content_sha256")),
    )
    op.create_index(
        "ix_documents_company_report_year", "documents", ["company_code", "report_year"]
    )
    op.create_index(
        "ix_documents_type_report_period", "documents",
        ["document_type", "report_period_end"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(length=500), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("vector_id", sa.String(length=100), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "chunk_index >= 0", name=op.f("ck_document_chunks_chunk_index_non_negative")
        ),
        sa.CheckConstraint(
            "chunk_version >= 1", name=op.f("ck_document_chunks_chunk_version_positive")
        ),
        sa.CheckConstraint(
            "page_start > 0", name=op.f("ck_document_chunks_page_start_positive")
        ),
        sa.CheckConstraint(
            "page_end >= page_start", name=op.f("ck_document_chunks_page_range_valid")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint(
            "document_id", "chunk_version", "chunk_index",
            name=op.f("uq_document_chunks_document_id_chunk_version_chunk_index"),
        ),
        sa.UniqueConstraint("vector_id", name=op.f("uq_document_chunks_vector_id")),
    )
    op.create_index(
        "ix_document_chunks_document_page", "document_chunks", ["document_id", "page_start"]
    )

    op.create_table(
        "document_ingestion_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "succeeded", "failed",
                name="documentingestionstatus", native_enum=False, length=16,
            ),
            server_default="pending", nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_document_ingestion_jobs_attempt_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name=op.f("fk_document_ingestion_jobs_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_ingestion_jobs")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_document_ingestion_jobs_idempotency_key")
        ),
    )
    op.create_index(
        "ix_document_ingestion_jobs_status_created_at", "document_ingestion_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_ingestion_jobs_status_created_at", table_name="document_ingestion_jobs"
    )
    op.drop_table("document_ingestion_jobs")
    op.drop_index("ix_document_chunks_document_page", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_type_report_period", table_name="documents")
    op.drop_index("ix_documents_company_report_year", table_name="documents")
    op.drop_table("documents")
