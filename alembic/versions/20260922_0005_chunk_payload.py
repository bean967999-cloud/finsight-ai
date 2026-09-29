"""Persist traceable chunk payloads while preserving legacy rows."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_0005"
down_revision: str | None = "20260922_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("parse_job_id", sa.Integer()))
    op.add_column("document_chunks", sa.Column("kind", sa.String(length=32)))
    op.add_column("document_chunks", sa.Column("content", sa.Text()))
    op.add_column("document_chunks", sa.Column("section_path", sa.JSON()))
    op.add_column("document_chunks", sa.Column("source_blocks", sa.JSON()))
    op.add_column("document_chunks", sa.Column("table_format", sa.String(length=16)))
    op.add_column("document_chunks", sa.Column("asset_path", sa.String(length=500)))
    op.create_foreign_key(
        "fk_document_chunks_parse_job_id_document_parse_jobs",
        "document_chunks", "document_parse_jobs", ["parse_job_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_document_chunks_parse_job_id", "document_chunks", ["parse_job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_parse_job_id", table_name="document_chunks")
    op.drop_constraint(
        "fk_document_chunks_parse_job_id_document_parse_jobs",
        "document_chunks", type_="foreignkey",
    )
    for name in (
        "asset_path", "table_format", "source_blocks", "section_path", "content", "kind",
        "parse_job_id",
    ):
        op.drop_column("document_chunks", name)
