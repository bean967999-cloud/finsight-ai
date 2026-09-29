"""Record the request fingerprint used by document ingestion idempotency."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0003"
down_revision: str | None = "20260921_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "document_ingestion_jobs",
        sa.Column("request_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_ingestion_jobs", "request_sha256")
