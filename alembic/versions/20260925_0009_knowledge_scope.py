"""Add workspace-owned knowledge bases and explicit document grants."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0009"
down_revision: str | None = "20260925_0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_knowledge_bases_workspace_id_name"),
    )
    op.create_table(
        "knowledge_base_grants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "knowledge_base_id", name="pk_knowledge_base_grants"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "knowledge_base_documents",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("knowledge_base_id", "document_id", name="pk_knowledge_base_documents"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_knowledge_base_documents_document_id", "knowledge_base_documents", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_base_documents_document_id", table_name="knowledge_base_documents")
    op.drop_table("knowledge_base_documents")
    op.drop_table("knowledge_base_grants")
    op.drop_table("knowledge_bases")
