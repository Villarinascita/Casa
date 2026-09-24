"""Promemoria e collegamento Telegram.

Revision ID: 20260924_01
Revises: c07f35093f53
"""

from alembic import op
import sqlalchemy as sa

from app.models import UTCDateTime

revision = "20260924_01"
down_revision = "c07f35093f53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("remind_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("repeat", sa.String(10), nullable=True))
        batch.create_check_constraint("ck_tasks_repeat", "repeat IS NULL OR repeat IN ('daily', 'weekly', 'monthly')")
        batch.create_check_constraint("ck_tasks_repeat_time", "repeat IS NULL OR remind_at IS NOT NULL")

    op.create_table("reminder_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("scheduled_at", UTCDateTime(), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(300)),
        sa.Column("sent_at", UTCDateTime()),
        sa.UniqueConstraint("task_id", "scheduled_at", name="uq_reminder_task_occurrence"),
    )
    op.create_index("ix_reminder_deliveries_task_id", "reminder_deliveries", ["task_id"])
    op.create_table("channel_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("external_user_id", sa.String(100), nullable=False),
        sa.Column("chat_id", sa.String(100), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("platform", "external_user_id", name="uq_channel_external_user"),
        sa.UniqueConstraint("user_id", "platform", name="uq_user_channel"),
    )
    op.create_index("ix_channel_links_household_id", "channel_links", ["household_id"])
    op.create_index("ix_channel_links_user_id", "channel_links", ["user_id"])
    op.create_table("telegram_link_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"])
    op.create_table("telegram_updates",
        sa.Column("update_id", sa.Integer(), primary_key=True),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("processed_at", UTCDateTime(), nullable=False),
    )
    op.create_table("telegram_pending",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
    )
    op.create_table("worker_cursors",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_cursors")
    op.drop_table("telegram_pending")
    op.drop_table("telegram_updates")
    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
    op.drop_index("ix_channel_links_user_id", table_name="channel_links")
    op.drop_index("ix_channel_links_household_id", table_name="channel_links")
    op.drop_table("channel_links")
    op.drop_index("ix_reminder_deliveries_task_id", table_name="reminder_deliveries")
    op.drop_table("reminder_deliveries")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_repeat_time", type_="check")
        batch.drop_constraint("ck_tasks_repeat", type_="check")
        batch.drop_column("repeat")
        batch.drop_column("remind_at")
