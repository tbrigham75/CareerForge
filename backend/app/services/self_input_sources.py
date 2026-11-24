"""Explicit period selection and immutable evidence for personal annual narratives."""
import hashlib
import json
from datetime import UTC, date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from docx import Document
from odf import teletype, text
from odf.opendocument import load
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Accomplishment, AttachmentMetadata
from app.services import reporting_year


def period(settings, year=None, start=None, end=None):
    if start or end:
        first, last = date.fromisoformat(start or ""), date.fromisoformat(end or "")
        if first > last:
            raise ValueError("The review start date must be on or before its end date.")
        return reporting_year.Period(first, last, f"{first} to {last}")
    if year:
        month = settings.start_month if settings.mode == "fiscal" else 1
        first_year = int(year) - (month != 1 and settings.year_naming == "ending")
        return reporting_year.period_for(date(first_year, month, 1), settings)
    return reporting_year.current_period(settings)


def catalog(session, selected_period):
    settings = reporting_year.preferences(session)
    zone = ZoneInfo(settings.timezone)
    ready, review, excluded = [], [], []
    records = session.scalars(select(Accomplishment).options(
        selectinload(Accomplishment.projects), selectinload(Accomplishment.evidence_references)
    ).where(Accomplishment.deleted_at.is_(None)).order_by(Accomplishment.date_completed, Accomplishment.title))
    for record in records:
        entered = record.created_at
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=UTC)
        entered_day = entered.astimezone(zone).date()
        finished = record.status in {"completed", "archived"}
        day = record.date_completed or entered_day
        in_period = selected_period.start <= day <= selected_period.end
        # Older ongoing work may still contribute; never assume it was completed.
        overlaps = not finished and (record.date_started or entered_day) <= selected_period.end
        spans_period = record.date_started is not None and record.date_started <= selected_period.end and day >= selected_period.start
        if not in_period and not overlaps and not spans_period:
            continue
        reason = ""
        if not record.report_inclusion:
            reason = "Include in reports is turned off"
        elif finished and not in_period:
            reason = "Completed outside this period; confirm only the contributions made within the review dates"
        elif not finished:
            reason = "Confirm the work contributed during this period; it is not marked completed"
        elif record.approval_status != "approved":
            reason = "Review and confirm this unapproved work"
        elif record.date_completed is None:
            reason = "Confirm timing: the original entry date is being used"
        row = {"record": record, "day": day, "reason": reason}
        (excluded if not record.report_inclusion else review if reason else ready).append(row)
    return {"ready": ready, "review": review, "excluded": excluded}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extract_document(content, suffix, warnings=None):
    warnings = warnings if warnings is not None else []
    if suffix in {".txt", ".md", ".csv"}:
        return content.decode("utf-8-sig")
    if suffix == ".pdf":
        from pypdf import PdfReader
        document = PdfReader(BytesIO(content))
        if document.is_encrypted or len(document.pages) > 100:
            raise ValueError("PDF must be unencrypted and no longer than 100 pages")
        pages = [page.extract_text() or "" for page in document.pages]
        if any(not value.strip() for value in pages):
            warnings.append("Some PDF pages have no extractable text; images and scans are not read")
        return "\n".join(pages)
    if suffix not in {".docx", ".odt"}:
        raise ValueError("Supported evidence formats: TXT, Markdown, CSV, DOCX, ODT and text-based PDF")
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
            raise ValueError("Document package exceeds extraction limits")
        if any("vbaproject" in item.filename.lower() for item in entries):
            raise ValueError("Macro-enabled evidence is unsupported")
    if suffix == ".docx":
        document = Document(BytesIO(content))
        if document.element.xpath(".//w:drawing | .//w:pict"):
            warnings.append("Embedded images are not read; only document text is included")
        # Read table paragraphs as well as ordinary paragraphs; never modify files.
        return "\n".join("".join(p.xpath(".//w:t/text()")) for p in document.element.xpath(".//w:p"))
    document = load(BytesIO(content))
    return "\n".join(teletype.extractText(p) for p in document.getElementsByType(text.P) + document.getElementsByType(text.H))


def attachment_snapshot(metadata, include_text):
    result = {"id": metadata.id, "name": metadata.original_filename, "hash": metadata.content_hash,
              "sensitivity": metadata.sensitivity, "text": "", "issue": ""}
    if not include_text:
        result["issue"] = "Document text excluded by your choice"
        return result
    try:
        root = (get_settings().data_dir / "attachments").resolve()
        path = Path(metadata.stored_path).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("Attachment is unavailable in managed storage")
        with path.open("rb") as stream:
            content = stream.read(25 * 1024 * 1024 + 1)
        if len(content) > 25 * 1024 * 1024:
            raise ValueError("Attachment exceeds the 25 MB extraction limit")
        if hashlib.sha256(content).hexdigest() != metadata.content_hash:
            raise ValueError("Attachment content changed; re-upload it before using it as evidence")
        warnings = []
        extracted = extract_document(content, Path(metadata.original_filename).suffix.lower(), warnings).strip()
        if not extracted:
            raise ValueError("No readable text; scanned documents need a text layer")
        if len(extracted) > 100000:
            raise ValueError("Document exceeds 100,000 characters; attach a relevant excerpt")
        result["text"] = extracted
        result["issue"] = "; ".join(warnings)
    except ImportError:
        result["issue"] = "PDF text reader is unavailable; install the project's pypdf dependency"
    except (ValueError, OSError, UnicodeError) as exc:
        result["issue"] = str(exc)[:300]
    except Exception:
        result["issue"] = "Document could not be read; use a supported, unencrypted text document"
    return result


def collect(session, selected_period, selected_ids, confirmed_ids, include_attachments):
    inventory = catalog(session, selected_period)
    allowed = {row["record"].id: row for key in ("ready", "review") for row in inventory[key]}
    if not selected_ids or any(key not in allowed for key in selected_ids):
        raise ValueError("Select at least one available accomplishment. Reload if a record changed.")
    unconfirmed = [allowed[key]["record"].title for key in selected_ids if allowed[key]["reason"] and key not in confirmed_ids]
    if unconfirmed:
        raise ValueError("Confirm these entries under Review included contributions, or leave them out: " + "; ".join(unconfirmed))
    sources = {}
    for key in selected_ids:
        row, record = allowed[key], allowed[key]["record"]
        attachments = session.scalars(select(AttachmentMetadata).where(AttachmentMetadata.accomplishment_id == key))
        snapshot = {"id": key, "title": record.title, "action": record.action, "metric": record.metric,
                    "impact": record.impact, "notes": record.supporting_narrative, "raw_note": record.raw_note,
                    "status": record.status, "approval": record.approval_status, "organization": record.organization,
                    "skills": record.skills, "competencies": record.competencies, "technologies": record.technologies,
                    "tags": record.tags, "categories": record.categories, "systems": record.systems, "keywords": record.keywords,
                    "date_started": str(record.date_started or ""), "date_completed": str(record.date_completed or ""),
                    "scope_date": str(row["day"]), "date_basis": "completion date" if record.date_completed else "original entry date",
                    "confirmation": row["reason"], "updated": record.updated_at.isoformat(),
                    "projects": [{"name": p.name, "description": p.description} for p in record.projects],
                    "references": [{"type": r.reference_type, "value": r.reference_value, "notes": r.notes} for r in record.evidence_references],
                    "attachments": [attachment_snapshot(a, include_attachments) for a in attachments]}
        snapshot["fingerprint"] = fingerprint(snapshot)
        sources[key] = snapshot
    return sources


def issues(sources):
    return [{"source_id": key, "name": attachment["name"], "issue": attachment["issue"]}
            for key, source in sources.items() for attachment in source["attachments"] if attachment["issue"]]
