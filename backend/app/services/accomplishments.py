from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.models import Accomplishment, AccomplishmentRevision, AuditEvent
from app.schemas import AccomplishmentInput


def snapshot(record: Accomplishment) -> dict[str, object]:
    return {
        "title": record.title,
        "raw_note": record.raw_note,
        "action": record.action,
        "metric": record.metric,
        "impact": record.impact,
        "supporting_narrative": record.supporting_narrative,
        "status": record.status,
        "sensitivity": record.sensitivity,
        "github_export": record.github_export,
        "approval_status": record.approval_status,
        "systems": record.systems,
        "technologies": record.technologies,
        "tags": record.tags,
        "categories": record.categories,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def record_revision(session: Session, record: Accomplishment, reason: str) -> None:
    revision = AccomplishmentRevision(
        accomplishment_id=record.id,
        revision_number=(
            session.scalar(
                select(func.count())
                .select_from(AccomplishmentRevision)
                .where(AccomplishmentRevision.accomplishment_id == record.id)
            )
            or 0
        )
        + 1,
        snapshot=snapshot(record),
        reason=reason,
    )
    session.add(revision)
    session.flush()


def create(session: Session, data: AccomplishmentInput) -> Accomplishment:
    title = data.title.strip() or (
        data.raw_note.strip()[:100] if data.raw_note else "Untitled accomplishment"
    )
    values = data.model_dump()
    values["title"] = title
    record = Accomplishment(**values)
    session.add(record)
    session.flush()
    record_revision(session, record, "created")
    session.add(AuditEvent(event_type="accomplishment.created", metadata_json={"id": record.id}))
    session.commit()
    session.refresh(record)
    return record


def update(
    session: Session, record: Accomplishment, data: AccomplishmentInput, reason: str = "edited"
) -> Accomplishment:
    for field, value in data.model_dump().items():
        setattr(record, field, value)
    if not record.title.strip():
        record.title = record.raw_note.strip()[:100] or "Untitled accomplishment"
    record.updated_at = datetime.now(UTC)
    session.flush()
    record_revision(session, record, reason)
    session.add(
        AuditEvent(
            event_type="accomplishment.updated", metadata_json={"id": record.id, "reason": reason}
        )
    )
    session.commit()
    session.refresh(record)
    return record


def archive(session: Session, record: Accomplishment, archived: bool) -> None:
    record.is_archived = archived
    session.flush()
    record_revision(session, record, "archived" if archived else "restored")
    session.add(
        AuditEvent(
            event_type="accomplishment.archived" if archived else "accomplishment.restored",
            metadata_json={"id": record.id},
        )
    )
    session.commit()


def soft_delete(session: Session, record: Accomplishment) -> None:
    record.deleted_at = datetime.now(UTC)
    session.add(AuditEvent(event_type="accomplishment.deleted", metadata_json={"id": record.id}))
    session.commit()


def search(
    session: Session, query: str = "", include_archived: bool = False
) -> list[Accomplishment]:
    statement = select(Accomplishment).where(Accomplishment.deleted_at.is_(None))
    if not include_archived:
        statement = statement.where(Accomplishment.is_archived.is_(False))
    if query.strip():
        like = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Accomplishment.title.ilike(like),
                Accomplishment.raw_note.ilike(like),
                Accomplishment.action.ilike(like),
                Accomplishment.tags.cast(String).ilike(like),
            )
        )
    return list(session.scalars(statement.order_by(Accomplishment.updated_at.desc())))
