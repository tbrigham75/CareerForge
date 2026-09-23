"""Add bounded AI provider retry configuration.

Revision ID: 0003_provider_retries
Revises: 0002_project_links
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_provider_retries"
down_revision = "0002_project_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("ai_providers")
    }
    if "retry_attempts" in columns:
        return
    with op.batch_alter_table("ai_providers") as batch:
        batch.add_column(
            sa.Column("retry_attempts", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_providers") as batch:
        batch.drop_column("retry_attempts")
