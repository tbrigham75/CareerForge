from __future__ import annotations

import hashlib
from pathlib import Path

from odf import teletype, text
from odf.opendocument import load
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Accomplishment, AuditEvent, ImportRun
from app.schemas import AccomplishmentInput
from app.services.accomplishments import create


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_odt(session: Session, source: Path) -> ImportRun:
    """Read a source document without modifying it; repeated identical sources are skipped."""
    source = source.resolve()
    digest = file_hash(source)
    previous = session.scalar(
        select(ImportRun).where(ImportRun.source_hash == digest, ImportRun.status == "completed")
    )
    if previous:
        run = ImportRun(
            source_path=str(source),
            filename=source.name,
            source_hash=digest,
            status="skipped_duplicate",
            imported_count=0,
        )
        session.add(run)
        session.add(
            AuditEvent(
                event_type="odt.import", metadata_json={"filename": source.name, "skipped": True}
            )
        )
        session.commit()
        return run
    document = load(str(source))
    paragraphs = [
        teletype.extractText(paragraph).strip() for paragraph in document.getElementsByType(text.P)
    ]
    paragraphs = [item for item in paragraphs if item]
    imported = 0
    for item in paragraphs:
        if len(item) < 20 or item.lower() in {"action:", "metric:", "impact:"}:
            continue
        exists = session.scalar(
            select(Accomplishment).where(
                Accomplishment.source_hash == hashlib.sha256(item.encode()).hexdigest()
            )
        )
        if not exists:
            record = create(
                session,
                AccomplishmentInput(raw_note=item, status="raw_note", sensitivity="internal"),
            )
            record.source_origin = "imported_odt"
            record.source_path = str(source)
            record.source_hash = hashlib.sha256(item.encode()).hexdigest()
            session.commit()
            imported += 1
    run = ImportRun(
        source_path=str(source),
        filename=source.name,
        source_hash=digest,
        status="completed",
        imported_count=imported,
    )
    session.add(run)
    session.add(
        AuditEvent(
            event_type="odt.import",
            metadata_json={"filename": source.name, "imported_count": imported},
        )
    )
    session.commit()
    return run
