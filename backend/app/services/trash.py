"""Trash lifecycle. Database removal queues file cleanup in the same transaction."""

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Accomplishment,
    AIDraft,
    AttachmentMetadata,
    AuditEvent,
    PendingFileDeletion,
    ReportItem,
)

RETENTION_DAYS = 30
lock = RLock()
logger = logging.getLogger(__name__)


def restore(session: Session, record: Accomplishment) -> None:
    record.deleted_at = None
    session.add(
        AuditEvent(event_type="accomplishment.trash_restored", metadata_json={"id": record.id})
    )
    session.commit()


def purge(session: Session, records: list[Accomplishment]) -> None:
    for record in records:
        if record.deleted_at is None:
            raise ValueError("Only items in Trash can be permanently deleted.")
        attachments = list(
            session.scalars(
                select(AttachmentMetadata).where(AttachmentMetadata.accomplishment_id == record.id)
            )
        )
        for attachment in attachments:
            session.add(PendingFileDeletion(stored_path=attachment.stored_path))
            session.delete(attachment)
        session.execute(delete(AIDraft).where(AIDraft.accomplishment_id == record.id))
        # Reports are independent historical snapshots, not dangling live references.
        session.execute(
            update(ReportItem)
            .where(ReportItem.accomplishment_id == record.id)
            .values(accomplishment_id=None)
        )
        session.add(
            AuditEvent(
                event_type="accomplishment.permanently_deleted", metadata_json={"id": record.id}
            )
        )
        session.delete(record)
    session.commit()
    cleanup_files(session)


def cleanup_files(session: Session) -> None:
    root = (get_settings().data_dir / "attachments").resolve()
    for pending in list(session.scalars(select(PendingFileDeletion))):
        try:
            path = Path(pending.stored_path)
            resolved = path.resolve()
            if root not in resolved.parents or path.is_symlink():
                raise ValueError("Unsafe attachment path; manual review required.")
            # Never remove a file still referenced by another attachment.
            referenced = session.scalar(
                select(AttachmentMetadata.id).where(
                    AttachmentMetadata.stored_path == pending.stored_path
                )
            )
            if not referenced:
                path.unlink(missing_ok=True)
                if resolved.parent != root:
                    with suppress(OSError):
                        resolved.parent.rmdir()  # Empty record folder only; never recursive.
            session.delete(pending)
        except (OSError, ValueError) as exc:
            pending.last_error = str(exc)
            logger.warning("Attachment cleanup pending: %s", pending.id)
        session.commit()


def maintenance(session: Session, now: datetime | None = None) -> None:
    with lock:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
        records = list(
            session.scalars(select(Accomplishment).where(Accomplishment.deleted_at <= cutoff))
        )
        purge(session, records)
