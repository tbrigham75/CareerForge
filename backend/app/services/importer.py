from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from odf import teletype, text
from odf.opendocument import load
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Accomplishment, AuditEvent, ImportRun
from app.schemas import AccomplishmentInput
from app.services.accomplishments import create


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_document(session: Session, source: Path) -> ImportRun:
    """Read a source document without modifying it; repeated identical sources are skipped."""
    source = source.resolve()
    suffix = source.suffix.lower()
    if suffix not in {".odt", ".docx"}:
        raise ValueError("Choose an ODT or Word (.docx) document. Save older .doc files as .docx first.")
    original_digest = file_hash(source)
    digest = hashlib.sha256(("structured-word-v2:" + original_digest).encode()).hexdigest() if suffix == ".docx" else original_digest
    legacy = session.scalar(select(ImportRun).where(ImportRun.source_hash == original_digest, ImportRun.status == "completed")) if suffix == ".docx" else None
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
                event_type=f"{suffix[1:]}.import", metadata_json={"filename": source.name, "skipped": True}
            )
        )
        session.commit()
        return run
    try:
        if suffix == ".docx":
            document = Document(str(source))
            entries = word_entries(document)
        else:
            odt_document = load(str(source))
            paragraphs = [
                teletype.extractText(paragraph).strip()
                for paragraph in odt_document.getElementsByType(text.P)
            ]
            entries = [AccomplishmentInput(raw_note=item, status="raw_note", sensitivity="internal") for item in paragraphs if len(item) >= 20]
    except Exception as exc:
        raise ValueError("Could not read this document. Choose a valid, unencrypted ODT or Word (.docx) file.") from exc
    imported = 0
    for entry in entries:
        item = entry.raw_note
        exists = session.scalar(
            select(Accomplishment).where(
                Accomplishment.source_hash == hashlib.sha256(item.encode()).hexdigest()
            )
        )
        if not exists:
            fragments = []
            if legacy and any((entry.action, entry.metric, entry.impact)):
                fragments = list(session.scalars(select(Accomplishment).where(
                    Accomplishment.source_path.in_({str(source), legacy.source_path}),
                    Accomplishment.source_origin == "imported_docx",
                    Accomplishment.raw_note.in_(item.splitlines()),
                    Accomplishment.deleted_at.is_(None),
                )))
                # Never replace notes that were edited, classified, or linked after import.
                if any(r.action or r.metric or r.impact or r.status != "raw_note"
                       or len(r.revisions) != 1 or r.projects or r.evidence_references
                       or r.is_archived or r.sensitivity != "internal"
                       or r.title != r.raw_note[:100]
                       or r.raw_note != r.revisions[0].snapshot.get("raw_note")
                       for r in fragments):
                    continue
            record = create(
                session,
                entry,
                commit=False,
            )
            record.source_origin = f"imported_{suffix[1:]}"
            record.source_path = str(source)
            record.source_hash = hashlib.sha256(item.encode()).hexdigest()
            for fragment in fragments:
                fragment.deleted_at = datetime.now(UTC)
                session.add(AuditEvent(event_type="import.fragment_replaced", metadata_json={"id": fragment.id, "replacement_id": record.id}))
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
            event_type=f"{suffix[1:]}.import",
            metadata_json={"filename": source.name, "imported_count": imported},
        )
    )
    session.commit()
    return run


def import_odt(session: Session, source: Path) -> ImportRun:
    """Compatibility entry point for existing scripts."""
    return import_document(session, source)


def field_label(value: str) -> str | None:
    match = re.match(r"^\s*(action|metrics?|metrix|impact)\b", value, re.I)
    if not match:
        return None
    label = match.group(1).lower()
    return "metric" if label in {"metrics", "metrix"} else label


def word_entries(document) -> list[AccomplishmentInput]:
    """Preserve labeled table rows and sections; never invent missing fields."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    entries = []
    pending: list[str] = []

    def flush():
        fields: dict[str, str] = {}
        raw: list[str] = []
        active = None

        def save():
            if raw and (fields or len("\n".join(raw)) >= 20):
                entries.append(AccomplishmentInput(raw_note="\n".join(raw), **fields,
                    status="raw_note", sensitivity="internal"))

        for value in pending:
            match = re.match(r"^\s*(?:#{1,6}\s*)?(action|metrics?|metrix|impact)\s*(?::|$)\s*(.*)", value, re.I)
            if match:
                label = field_label(match.group(1))
                if label in fields:
                    save()
                    fields, raw = {}, []
                active = label
                fields[active] = match.group(2).strip()
                raw.append(value)
            elif active:
                raw.append(value)
                fields[active] = "\n".join(filter(None, [fields[active], value]))
            else:
                if len(value) >= 20:
                    entries.append(AccomplishmentInput(raw_note=value, status="raw_note", sensitivity="internal"))
        save()
        pending.clear()

    for block in document.element.body:
        if block.tag.endswith("}p"):
            value = Paragraph(block, document).text.strip()
            if value:
                pending.extend(value.splitlines())
        elif block.tag.endswith("}tbl"):
            flush()
            table = Table(block, document)
            headers = {}
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                labels = {index: field_label(value) for index, value in enumerate(cells)}
                recognized = {i: label for i, label in labels.items() if label}
                if len(set(recognized.values())) >= 2:
                    headers = recognized
                    continue
                if headers:
                    fields = {label: cells[i] for i, label in headers.items() if i < len(cells)}
                    if any(fields.values()):
                        entries.append(AccomplishmentInput(raw_note="\n".join(cells), **fields,
                            status="raw_note", sensitivity="internal"))
                elif len(cells) == 2 and field_label(cells[0]):
                    pending.append(f"{field_label(cells[0])}: {cells[1]}")
                else:
                    pending.extend(value for value in cells if value)
            flush()
    flush()
    return entries
