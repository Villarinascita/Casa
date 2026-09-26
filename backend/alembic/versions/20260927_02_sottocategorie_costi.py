"""sottocategoria dei costi

Revision ID: 20260927_02
Revises: 20260927_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_02"
down_revision = "20260927_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bills", sa.Column("subcategory", sa.String(60)))


def downgrade() -> None:
    with op.batch_alter_table("bills") as batch:
        batch.drop_column("subcategory")
