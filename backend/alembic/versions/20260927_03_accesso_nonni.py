"""accesso «nonno»: ruolo che vede solo la settimana dei nonni

Revision ID: 20260927_03
Revises: 20260927_02
"""

from alembic import op

revision = "20260927_03"
down_revision = "20260927_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # household_users non è referenziata da altre tabelle: ricrearla per cambiare il vincolo è sicuro.
    with op.batch_alter_table("household_users", recreate="always") as batch:
        batch.drop_constraint("ck_household_users_role", type_="check")
        batch.create_check_constraint("ck_household_users_role", "role IN ('admin', 'adult', 'nonno')")


def downgrade() -> None:
    op.execute("DELETE FROM household_users WHERE role = 'nonno'")
    with op.batch_alter_table("household_users", recreate="always") as batch:
        batch.drop_constraint("ck_household_users_role", type_="check")
        batch.create_check_constraint("ck_household_users_role", "role IN ('admin', 'adult')")
