from __future__ import annotations

from docx import Document
from docx.shared import Inches, Pt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Accomplishment, AuditEvent, Report, ReportItem


def generate_docx(
    session: Session, title: str, records: list[Accomplishment], report_type: str = "custom"
) -> Report:
    document = Document()
    document.sections[0].top_margin = Inches(0.75)
    style = document.styles["Normal"]
    style.font.name = "Aptos"
    style.font.size = Pt(10)
    document.add_heading(title, 0)
    document.add_paragraph(f"CareerForge {report_type.title()} report")
    report = Report(title=title, report_type=report_type)
    session.add(report)
    session.flush()
    for position, record in enumerate(records, start=1):
        document.add_heading(record.title, level=1)
        for heading, content in (
            ("Action", record.action),
            ("Metric", record.metric),
            ("Impact", record.impact),
        ):
            document.add_heading(heading, level=2)
            document.add_paragraph(content or "[Not provided]")
        if record.supporting_narrative:
            document.add_heading("Supporting details", level=2)
            document.add_paragraph(record.supporting_narrative)
        session.add(
            ReportItem(
                report_id=report.id,
                accomplishment_id=record.id,
                position=position,
                source_snapshot={
                    "title": record.title,
                    "action": record.action,
                    "metric": record.metric,
                    "impact": record.impact,
                },
            )
        )
    safe_name = (
        "-".join("".join(char if char.isalnum() else " " for char in title).split()).lower()
        or "careerforge-report"
    )
    output = get_settings().data_dir / "reports" / f"{safe_name}-{report.id[:8]}.docx"
    document.save(str(output))
    report.output_path = str(output)
    session.add(
        AuditEvent(
            event_type="report.generated",
            metadata_json={"report_id": report.id, "record_count": len(records)},
        )
    )
    session.commit()
    return report
