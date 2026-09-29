"""Ricorrenze e promemoria per appuntamenti.

Revision ID: 20260929_01
Revises: 20260927_04
"""
import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision = '20260929_01'
down_revision = '20260927_04'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('events', sa.Column('series_id', sa.String(36), nullable=True))
    op.add_column('events', sa.Column('reminder_minutes', sa.Integer(), nullable=True))
    op.create_index('ix_events_series_id', 'events', ['series_id'])
    op.create_table('event_reminder_deliveries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('event_id', sa.String(36), sa.ForeignKey('events.id'), nullable=False),
        sa.Column('scheduled_at', UTCDateTime(), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(300)),
        sa.Column('sent_at', UTCDateTime()),
        sa.UniqueConstraint('event_id', 'scheduled_at', name='uq_event_reminder_occurrence'))
    op.create_index('ix_event_reminder_deliveries_event_id', 'event_reminder_deliveries', ['event_id'])
    op.create_index('ix_event_reminder_deliveries_status', 'event_reminder_deliveries', ['status'])


def downgrade():
    op.drop_table('event_reminder_deliveries')
    op.drop_index('ix_events_series_id', table_name='events')
    with op.batch_alter_table('events') as batch:
        batch.drop_column('reminder_minutes')
        batch.drop_column('series_id')
