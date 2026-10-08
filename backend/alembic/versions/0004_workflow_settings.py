"""Reusable label identities, systems/services, and report template settings.

Legacy duplicate rows are retained with distinct identities, never deleted.
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0004_workflow_settings"
down_revision = "0003_provider_retries"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "system_services" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "system_services",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(150), nullable=False, unique=True),
            sa.Column("name_key", sa.String(300), nullable=False, unique=True),
        )
    for table in ("categories", "tags", "technologies", "skills", "competencies"):
        if "name_key" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            continue
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("name_key", sa.String(300), nullable=True))
        seen = set()
        for row in bind.execute(
            sa.text(f"SELECT id, name FROM {table} ORDER BY name, id")
        ).mappings():
            key = row["name"].strip().casefold()
            identity = key if key not in seen else "__legacy_duplicate__:" + row["id"]
            seen.add(key)
            bind.execute(
                sa.text(f"UPDATE {table} SET name_key=:key WHERE id=:id"),
                {"key": identity, "id": row["id"]},
            )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("name_key", existing_type=sa.String(300), nullable=False)
            batch.create_unique_constraint(f"uq_{table}_name_key", ["name_key"])
    if "settings" not in {c["name"] for c in sa.inspect(bind).get_columns("report_templates")}:
        with op.batch_alter_table("report_templates") as batch:
            batch.add_column(sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"))
        for row in bind.execute(sa.text("SELECT id, content FROM report_templates")).mappings():
            bind.execute(
                sa.text("UPDATE report_templates SET settings=:settings WHERE id=:id"),
                {"id": row["id"], "settings": json.dumps({"content": row["content"]})},
            )


def downgrade():
    with op.batch_alter_table("report_templates") as batch:
        batch.drop_column("settings")
    for table in ("categories", "tags", "technologies", "skills", "competencies"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_name_key", type_="unique")
            batch.drop_column("name_key")
    op.drop_table("system_services")
