# Database Maintenance and project editing

Settings → Database Maintenance shows database allocation, reusable space, uploaded
document storage, Trash count, and pending file cleanup. Refresh updates the totals.
Health checks run SQLite integrity_check and foreign_key_check without modifying records.
Failures are diagnostic only: no automatic repair or broad orphan deletion is attempted.

Retry file cleanup processes only the durable deletion queue. Review errors and deleted
records in Settings → Trash. The existing 30-day lifecycle remains unchanged.

Optional compaction requires typing COMPACT. It checks health, creates and verifies a
database-only SQLite backup in the local backups folder, then runs VACUUM. The SQLite
backup API produces a consistent database snapshot even with live connections. Backup
waiting is bounded, and SQLite lock contention returns a retryable error. Avoid editing
while compaction runs. Existing backups, reports, attachments and Trash are not erased.
The snapshot does not include documents: use Backups for a full application backup.
Backups accumulate intentionally; this feature never deletes them automatically.

All maintenance actions require authentication and CSRF protection. Compaction and
cleanup are audit logged. SQLite normally reuses free space without manual maintenance.

Projects → select the project name → edit name/description → Save project. Validation
preserves submitted input. Project IDs and accomplishment associations remain unchanged.
