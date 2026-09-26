"""pubblicità nel cestino in automatico

Revision ID: 20260926_02
Revises: 20260926_01
"""

import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision = "20260926_02"
down_revision = "20260926_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("email_auto_trash",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("message_id", sa.String(200), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("trashed_at", UTCDateTime(), nullable=False),
        sa.Column("reported_at", UTCDateTime()))
    op.create_index("ix_email_auto_trash_household_id", "email_auto_trash", ["household_id"])
    op.create_index("ix_email_auto_trash_connection_id", "email_auto_trash", ["connection_id"])


def downgrade() -> None:
    op.drop_table("email_auto_trash")
