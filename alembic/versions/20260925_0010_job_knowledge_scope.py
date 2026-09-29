"""Attach new document tasks to a knowledge base; legacy jobs remain unscoped."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0010"
down_revision: str | None = "20260925_0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("async_jobs", sa.Column("knowledge_base_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_async_jobs_knowledge_base_id_knowledge_bases",
        "async_jobs", "knowledge_bases", ["knowledge_base_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_async_jobs_knowledge_base_id", "async_jobs", ["knowledge_base_id"])


def downgrade() -> None:
    op.drop_index("ix_async_jobs_knowledge_base_id", table_name="async_jobs")
    op.drop_constraint("fk_async_jobs_knowledge_base_id_knowledge_bases", "async_jobs", type_="foreignkey")
    op.drop_column("async_jobs", "knowledge_base_id")
