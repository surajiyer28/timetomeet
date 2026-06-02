"""agent_chat_messages — the user's private conversation with their own agent

Revision ID: 002
Revises: 001
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),  # 'user' | 'agent'
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_chat_user_created", "agent_chat_messages", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_chat_user_created", table_name="agent_chat_messages")
    op.drop_table("agent_chat_messages")
