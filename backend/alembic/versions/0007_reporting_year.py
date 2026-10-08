"""Organization reporting calendar; no accomplishment changes."""

import sqlalchemy as sa

from alembic import op

revision = "0007_reporting_year"
down_revision = "0006_trash"
branch_labels = None
depends_on = None


def upgrade():
    if "reporting_settings" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "reporting_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("start_month", sa.Integer(), nullable=False),
            sa.Column("year_naming", sa.String(20), nullable=False),
            sa.Column("timezone", sa.String(100), nullable=False),
        )


def downgrade():
    op.drop_table("reporting_settings")
