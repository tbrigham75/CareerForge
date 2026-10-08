# Archive and Trash lifecycle

Archive is indefinite storage accessible from Accomplishments → Include archived.
Open a record and choose Restore from archive to return it to the active list.

Move to trash hides an accomplishment and its attachment downloads. Settings → Trash
lists deletion/expiration times (UTC), remaining days, project links, and prior archive
status. Restore preserves all fields, relationships, revisions, and documents.

Permanent deletion requires typing DELETE; Empty trash requires EMPTY TRASH.
Both are authenticated, CSRF-protected POST operations. Only trashed items qualify.
Expired trash is purged at startup and hourly while the application runs. When the
application is off no cleanup occurs; overdue items are removed on the next startup.
Migration 0006 gives existing deleted records a fresh 30-day window exactly once.

Deletion removes revisions, evidence, AI drafts, project associations, and attachment
metadata. Projects and taxonomy remain. Report items retain immutable snapshots with
a nullable source link, so existing reports can still be reordered and regenerated.
Reports, exports, backup copies, and minimal audit history are not erased by Trash.

File removal is queued durably in the same database transaction as record deletion.
An interrupted cleanup resumes on the next run. Only paths resolving inside the
managed attachments folder qualify; deletion is never recursive. Shared referenced
files are retained. Locked or unsafe files remain in the queue; Settings → Trash shows
errors and offers Retry file cleanup. Investigate unsafe paths rather than broadening
the allowed deletion root. Unexpected maintenance failures appear in server logs.

SQLite reuses freed database space. Routine VACUUM is unnecessary; this feature does
not automatically shrink the database or prune backups. Run one application worker
(the supported local deployment); lifecycle actions use an in-process lock.
