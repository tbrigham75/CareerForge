"""Add accomplishment-project links.

Revision ID: 0002_project_links
Revises: 0001_initial
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_project_links"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_accomplishments",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("accomplishment_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["accomplishment_id"], ["accomplishments.id"]),
        sa.PrimaryKeyConstraint("project_id", "accomplishment_id"),
    )


def downgrade() -> None:
    op.drop_table("project_accomplishments")
