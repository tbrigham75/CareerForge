"""Preserved resumes and reviewed version history."""
from alembic import op
import sqlalchemy as sa

revision = "0008_resumes"
down_revision = "0007_reporting_year"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("resumes", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("name", sa.String(300), nullable=False),
                    sa.Column("original_path", sa.Text(), nullable=False),
                    sa.Column("original_hash", sa.String(64), nullable=False),
                    sa.Column("state", sa.JSON(), nullable=False),
                    sa.Column("revision", sa.Integer(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("resumes")
