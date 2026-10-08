"""Install eight editable starter report templates once."""

from alembic import op
from app.services.starter_report_templates import seed_starter_templates

revision = "0005_starter_reports"
down_revision = "0004_workflow_settings"
branch_labels = None
depends_on = None


def upgrade():
    seed_starter_templates(op.get_bind())


def downgrade():
    # Templates may have been edited. Retain them rather than deleting user content.
    pass
