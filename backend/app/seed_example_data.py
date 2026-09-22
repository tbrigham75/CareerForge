from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment
from app.schemas import AccomplishmentInput
from app.services.accomplishments import create


def main() -> None:
    examples = [
        AccomplishmentInput(
            title="Patched CVE-affected applications",
            raw_note="Patched four CVE-affected applications on Easley.",
            action="Patched four CVE-affected applications in the Easley environment.",
            metric="Completed remediation within three days of vulnerability notification.",
            impact="Reduced exposure to the identified vulnerabilities; confirm final validation scope.",
            systems=["Easley"],
            tags=["CVE", "patch-management"],
            technologies=["Linux"],
            categories=["Security"],
            sensitivity="internal",
            status="completed",
            approval_status="approved",
        ),
        AccomplishmentInput(
            title="Consolidated CSPAN form navigation",
            raw_note="Consolidated 15 CSPAN forms into a single drop-down menu.",
            action="Consolidated 15 CSPAN forms into a single drop-down menu.",
            metric="Simplified navigation across 15 previously separate forms.",
            impact="Reduced the effort required for users to locate the appropriate form; confirm measured user outcome.",
            sensitivity="internal",
            status="completed",
            approval_status="approved",
        ),
    ]
    with SessionLocal() as session:
        for item in examples:
            if not session.scalar(select(Accomplishment).where(Accomplishment.title == item.title)):
                create(session, item)


if __name__ == "__main__":
    main()
