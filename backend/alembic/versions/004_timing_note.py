"""carry the initiator's timing preference (e.g. "Thursday", "next week afternoon") into a session

Revision ID: 004
Revises: 003
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduling_sessions", sa.Column("timing_note", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("scheduling_sessions", "timing_note")
