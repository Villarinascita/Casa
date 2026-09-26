"""doppioni e abitudini: provenienza di appuntamenti/attività e feedback

Revision ID: 20260927_01
Revises: 20260926_02
"""

import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision = "20260927_01"
down_revision = "20260926_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD COLUMN semplice: niente ricreazione delle tabelle (events e tasks hanno righe collegate).
    op.add_column("events", sa.Column("source_sender", sa.String(320)))
    op.add_column("tasks", sa.Column("source", sa.String(40), nullable=False, server_default="manual"))
    op.add_column("tasks", sa.Column("source_sender", sa.String(320)))
    op.create_table("email_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("sender", sa.String(320)),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("entity_id", sa.String(36)),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("verdict IN ('kept', 'discarded')", name="ck_email_feedback_verdict"))
    op.create_index("ix_email_feedback_household_id", "email_feedback", ["household_id"])
    op.create_index("ix_email_feedback_entity_id", "email_feedback", ["entity_id"])


def downgrade() -> None:
    op.drop_table("email_feedback")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("source_sender")
        batch.drop_column("source")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("source_sender")
