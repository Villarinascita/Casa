"""programma dei nonni caricato da file

Revision ID: 20260927_04
Revises: 20260927_03
"""

import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision = "20260927_04"
down_revision = "20260927_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("grandparent_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(1000)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("applied_at", UTCDateTime()),
        sa.CheckConstraint("status IN ('reading', 'pending', 'failed', 'applied', 'discarded')",
                           name="ck_grandparent_plans_status"))
    op.create_index("ix_grandparent_plans_household_id", "grandparent_plans", ["household_id"])


def downgrade() -> None:
    op.drop_table("grandparent_plans")
