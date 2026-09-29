"""Track PDF parse attempts separately from original document ingestion."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0004"
down_revision: str | None = "20260921_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "document_parse_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=36)),
        sa.Column("parser_name", sa.String(length=100)),
        sa.Column("parser_version", sa.String(length=50)),
        sa.Column("page_count", sa.Integer()),
        sa.Column("markdown_key", sa.String(length=500)),
        sa.Column("content_list_key", sa.String(length=500)),
        sa.Column("middle_json_key", sa.String(length=500)),
        sa.Column("parsed_document_key", sa.String(length=500)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_document_parse_jobs_document_created", "document_parse_jobs", ["document_id", "created_at"]
    )
    op.create_index(
        "ix_document_parse_jobs_status_created", "document_parse_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_parse_jobs_status_created", table_name="document_parse_jobs")
    op.drop_index("ix_document_parse_jobs_document_created", table_name="document_parse_jobs")
    op.drop_table("document_parse_jobs")
