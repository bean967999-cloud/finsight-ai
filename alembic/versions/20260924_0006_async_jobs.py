"""Persist orchestration jobs independently of document parse attempts."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0006"
down_revision: str | None = "20260922_0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "async_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("task_kind", sa.String(length=32), nullable=False),
        sa.Column("task_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("result_ref", sa.String(length=200)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_async_jobs_attempt_count_nonnegative"),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10", name="ck_async_jobs_max_attempts_range"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_async_jobs_idempotency_key"),
    )
    op.create_index("ix_async_jobs_status_created_at", "async_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_async_jobs_status_created_at", table_name="async_jobs")
    op.drop_table("async_jobs")
