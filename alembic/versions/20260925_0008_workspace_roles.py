"""Persist workspaces and one role per user in each workspace."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0008"
down_revision: str | None = "20260925_0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_workspaces_name"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "workspace_id", name="pk_workspace_memberships"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role IN ('viewer', 'researcher', 'reviewer', 'workspace_admin')",
            name="ck_workspace_memberships_role_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_memberships")
    op.drop_table("workspaces")
