"""Record sensitive HTTP operation metadata without request bodies or credentials."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0011"
down_revision: str | None = "20260925_0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("route_pattern", sa.String(length=120), nullable=False),
        sa.Column("target_id", sa.String(length=128)),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("knowledge_base_id", sa.Uuid()),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_audit_events_actor_started", "audit_events", ["actor_user_id", "started_at"])
    op.create_index("ix_audit_events_workspace_started", "audit_events", ["workspace_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_workspace_started", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_started", table_name="audit_events")
    op.drop_table("audit_events")
