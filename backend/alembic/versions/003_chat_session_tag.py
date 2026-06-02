"""tag home-channel messages with an optional session (the per-meeting agent trace)

Revision ID: 003
Revises: 002
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_chat_messages",
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("scheduling_sessions.id", ondelete="CASCADE"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_chat_messages", "session_id")
