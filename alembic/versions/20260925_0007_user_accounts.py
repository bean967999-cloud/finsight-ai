"""Create local user identities without self-registration."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0007"
down_revision: str | None = "20260924_0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
    )


def downgrade() -> None:
    op.drop_table("user_accounts")
