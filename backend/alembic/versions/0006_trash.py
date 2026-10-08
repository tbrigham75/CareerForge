"""Recoverable trash and durable attachment cleanup."""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0006_trash"
down_revision = "0005_starter_reports"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "pending_file_deletions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "pending_file_deletions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=False),
        )
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("report_items")}
    if not columns["accomplishment_id"]["nullable"]:
        with op.batch_alter_table("report_items") as batch:
            batch.alter_column("accomplishment_id", existing_type=sa.String(36), nullable=True)
    # One-time grace period for all records deleted before Trash was available.
    op.get_bind().execute(
        sa.text("UPDATE accomplishments SET deleted_at = :now WHERE deleted_at IS NOT NULL"),
        {"now": datetime.now(UTC).replace(tzinfo=None)},
    )


def downgrade():
    raise RuntimeError("Trash migration cannot be reversed without losing detached report history.")
