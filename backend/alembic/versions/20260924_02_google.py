"""Google OAuth, Gmail proposals and Calendar sync.

Revision ID: 20260924_02
Revises: 20260924_01
"""

from alembic import op
import sqlalchemy as sa

from app.models import UTCDateTime

revision = "20260924_02"
down_revision = "20260924_01"
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
    op.create_table("google_oauth_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False))
    op.create_table("google_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("gmail_query", sa.String(500), nullable=False),
        sa.Column("gmail_history_id", sa.String(100)),
        sa.Column("gmail_page_token", sa.String(500)),
        sa.Column("last_gmail_sync_at", UTCDateTime()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("created_at", UTCDateTime(), nullable=False))
    op.create_index("ix_google_connections_household_id", "google_connections", ["household_id"])
    op.create_table("google_calendars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("outbound_default", sa.Boolean(), nullable=False),
        sa.Column("sync_token", sa.Text()),
        sa.Column("last_synced_at", UTCDateTime()),
        sa.Column("last_full_sync_at", UTCDateTime()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_google_calendar_connection_external"),
        sa.CheckConstraint("mode IN ('full', 'busy')", name="ck_google_calendars_mode"))
    op.create_index("ix_google_calendars_connection_id", "google_calendars", ["connection_id"])
    op.create_table("email_processed",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("processed_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("connection_id", "message_id", name="uq_email_processed_message"))
    op.create_index("ix_email_processed_connection_id", "email_processed", ["connection_id"])
    op.create_table("proposals", *_entity_columns(),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.String(500)),
        sa.Column("snippet", sa.String(500)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("target_id", sa.String(36)),
        sa.UniqueConstraint("connection_id", "message_id", "item_index", name="uq_proposal_email_item"))
    op.create_index("ix_proposals_household_id", "proposals", ["household_id"])
    op.create_index("ix_proposals_connection_id", "proposals", ["connection_id"])
    op.create_table("calendar_event_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("google_calendars.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("etag", sa.String(200)),
        sa.Column("local_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("remote_payload", sa.JSON()),
        sa.Column("last_synced_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("calendar_id", "external_id", name="uq_calendar_external_event"))
    op.create_index("ix_calendar_event_links_calendar_id", "calendar_event_links", ["calendar_id"])


def downgrade() -> None:
    op.drop_table("calendar_event_links")
    op.drop_table("proposals")
    op.drop_table("email_processed")
    op.drop_table("google_calendars")
    op.drop_table("google_connections")
    op.drop_table("google_oauth_states")
