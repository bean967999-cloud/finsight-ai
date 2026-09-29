"""Persist bounded research diagnostics with server-resolved ownership."""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0012"
down_revision = "20260925_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_traces",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid()),
        sa.Column("frames", sa.JSON(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_research_traces_workspace_owner", "research_traces", ["workspace_id", "owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_research_traces_workspace_owner", table_name="research_traces")
    op.drop_table("research_traces")
