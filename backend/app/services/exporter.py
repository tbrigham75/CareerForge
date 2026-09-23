from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Accomplishment, AuditEvent, ExportRun


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "accomplishment"


def markdown_for(record: Accomplishment) -> str:
    metadata = {
        "id": record.id,
        "title": record.title,
        "date_completed": str(record.date_completed or ""),
        "categories": record.categories,
        "tags": record.tags,
        "technologies": record.technologies,
        "systems": record.systems,
        "sensitivity": record.sensitivity,
        "github_export": record.github_export,
        "source_updated_at": record.updated_at.isoformat(),
        "source_origin": record.source_origin,
    }
    front_matter = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
    )
    return f"---\n{front_matter}\n---\n\n# {record.title}\n\n## Action\n\n{record.action}\n\n## Metric\n\n{record.metric}\n\n## Impact\n\n{record.impact}\n\n## Supporting details\n\n{record.supporting_narrative}\n"


def export_markdown(
    session: Session, destination: Path, dry_run: bool = True, profile_id: str | None = None
) -> dict[str, object]:
    records = list(
        session.scalars(
            select(Accomplishment).where(
                Accomplishment.deleted_at.is_(None),
                Accomplishment.github_export.is_(True),
                Accomplishment.approval_status == "approved",
                Accomplishment.sensitivity.in_(["public_safe", "private_personal", "internal"]),
            )
        )
    )
    files: list[str] = []
    for record in records:
        filename = f"{record.date_completed or record.created_at.date()}-{_slug(record.title)}-{record.id[:8]}.md"
        files.append(filename)
        if not dry_run:
            destination.mkdir(parents=True, exist_ok=True)
            (destination / filename).write_text(markdown_for(record), encoding="utf-8")
    manifest = {"generated_at": datetime.now(UTC).isoformat(), "dry_run": dry_run, "files": files}
    run = ExportRun(
        profile_id=profile_id,
        status="dry_run" if dry_run else "completed",
        manifest=manifest,
    )
    session.add(run)
    session.add(
        AuditEvent(
            event_type="markdown.export", metadata_json={"dry_run": dry_run, "count": len(files)}
        )
    )
    session.commit()
    return manifest
