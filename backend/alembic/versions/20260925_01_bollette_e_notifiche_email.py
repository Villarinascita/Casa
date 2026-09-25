"""Bollette e costi di casa, notifiche di controllo per creazioni da email.

Revision ID: 20260925_01
Revises: 20260924_02
"""

from alembic import op
import sqlalchemy as sa

from app.models import UTCDateTime

revision = "20260925_01"
down_revision = "20260924_02"
branch_labels = None
depends_on = None


def _entity_columns():
    return [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("created_at", UTCDateTime(), nullable=False),
            sa.Column("updated_at", UTCDateTime(), nullable=False),
            sa.Column("deleted_at", UTCDateTime()),
            sa.Column("version", sa.Integer(), nullable=False)]


def upgrade() -> None:
    op.create_table("bills", *_entity_columns(),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("supplier", sa.String(180)),
        sa.Column("amount", sa.Numeric(10, 2)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("payment_state", sa.String(20), nullable=False),
        sa.Column("source_sender", sa.String(320)),
        sa.Column("source_subject", sa.String(500)),
        sa.Column("found_reminder_sent_at", UTCDateTime()),
        sa.Column("due_reminder_sent_at", UTCDateTime()),
        sa.CheckConstraint("payment_state IN ('da_pagare', 'addebito_previsto', 'pagato')",
                           name="ck_bills_payment_state"))
    op.create_index("ix_bills_household_id", "bills", ["household_id"])
    op.create_index("ix_bills_household_payment_due", "bills", ["household_id", "payment_state", "due_date"])
    op.create_table("email_creation_notices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("entity_type", sa.String(10), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("sent_at", UTCDateTime()),
        sa.CheckConstraint("entity_type IN ('event', 'task')", name="ck_email_creation_notices_entity_type"))
    op.create_index("ix_email_creation_notices_household_id", "email_creation_notices", ["household_id"])


def downgrade() -> None:
    op.drop_table("email_creation_notices")
    op.drop_table("bills")
