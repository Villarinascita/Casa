"""Pulizia retroattiva delle email dei domini bloccati.

Revision ID: 20260926_01
Revises: 20260925_01
"""

from alembic import op
import sqlalchemy as sa

from app.models import UTCDateTime

revision = "20260926_01"
down_revision = "20260925_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("email_domain_cleanups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("domain", sa.String(320), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("page_token", sa.String(500)),
        sa.Column("trashed_count", sa.Integer(), nullable=False),
        sa.Column("failed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("completed_at", UTCDateTime()),
        sa.CheckConstraint("status IN ('running', 'done')", name="ck_email_domain_cleanups_status"))
    op.create_index("ix_email_domain_cleanups_household_id", "email_domain_cleanups", ["household_id"])
    op.create_index("ix_email_domain_cleanups_connection_id", "email_domain_cleanups", ["connection_id"])


def downgrade() -> None:
    op.drop_table("email_domain_cleanups")
