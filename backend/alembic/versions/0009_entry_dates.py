"""Use original entry dates for previously undated records, as requested."""
import json
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = '0009_entry_dates'
down_revision = '0008_resumes'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    timezone = connection.execute(sa.text('SELECT timezone FROM reporting_settings WHERE id=1')).scalar() or 'UTC'
    zone = ZoneInfo(timezone)
    rows = connection.execute(sa.text('SELECT id, created_at, date_started FROM accomplishments WHERE date_completed IS NULL AND deleted_at IS NULL')).mappings().all()
    changed, conflicts = [], []
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(' ')
    for row in rows:
        timestamp = datetime.fromisoformat(str(row['created_at']))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        day = timestamp.astimezone(zone).date().isoformat()
        if row['date_started'] and str(row['date_started'])[:10] > day:
            conflicts.append(row['id'])
            continue
        connection.execute(sa.text('UPDATE accomplishments SET date_completed=:day, updated_at=:now WHERE id=:id AND date_completed IS NULL'), {'day': day, 'now': now, 'id': row['id']})
        changed.append({'id': row['id'], 'entry_date': day})
    connection.execute(sa.text('INSERT INTO audit_events (id,event_type,outcome,metadata_json,created_at) VALUES (:id,:event,:outcome,:metadata,:now)'),
                       {'id': str(uuid.uuid4()), 'event': 'accomplishment.entry_dates_defaulted', 'outcome': 'success', 'metadata': json.dumps({'records': changed, 'start_date_conflicts': conflicts, 'timezone': timezone}), 'now': now})


def downgrade():
    # User data corrections are retained; never erase dates subsequently reviewed.
    pass
