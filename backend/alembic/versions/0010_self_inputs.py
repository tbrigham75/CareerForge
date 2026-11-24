"""Reviewed year-end narratives, source snapshots and approved versions."""
import sqlalchemy as sa

from alembic import op

revision = "0010_self_inputs"
down_revision = "0009_entry_dates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "self_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("self_inputs")
