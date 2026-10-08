"""Version-one starter catalog. Seed once; never overwrite user edits or deletions."""

import json
import uuid

from sqlalchemy import text

STARTERS = [
    (
        "Executive Summary",
        "Executive Accomplishment Summary",
        "custom",
        "impact_first",
        "Selected accomplishments presented with outcomes first, followed by the work and confirmed scope supporting those outcomes.",
        "executive-summary.docx",
    ),
    (
        "Monthly Update",
        "Monthly Accomplishment Update",
        "monthly",
        "compact",
        "A concise record of work completed during the selected month, including actions, scope, and outcomes.",
        "monthly-update.docx",
    ),
    (
        "Quarterly Review",
        "Quarterly Accomplishment Review",
        "quarterly",
        "impact_first",
        "A review of selected quarterly contributions and their documented impact. Supporting details provide context for the results.",
        "quarterly-review.docx",
    ),
    (
        "Annual Self-Assessment",
        "Annual Performance Self-Assessment",
        "annual",
        "detailed",
        "A factual record of selected contributions for the performance-review period. Each entry connects the work performed with its confirmed scope and impact.",
        "annual-self-assessment.docx",
    ),
    (
        "Promotion Evidence",
        "Career Progression Evidence",
        "custom",
        "impact_first",
        "Selected contributions supporting a career-progression discussion. Entries document demonstrated work, its scope, and outcomes without assuming a promotion decision or level.",
        "promotion-evidence.docx",
    ),
    (
        "Project Closeout",
        "Project Closeout Accomplishments",
        "custom",
        "detailed",
        "A record of selected project contributions and outcomes for handoff and closeout discussions. Select only the accomplishments relevant to the project.",
        "project-closeout.docx",
    ),
    (
        "Security & Compliance",
        "Security and Compliance Contributions",
        "custom",
        "detailed",
        "Selected security assessment, remediation, and compliance-support work. These entries document contributions and evidence; they do not by themselves certify compliance or risk acceptance.",
        "security-compliance.docx",
    ),
    (
        "Technical Operations",
        "Technical Operations Summary",
        "monthly",
        "compact",
        "Selected systems administration, service maintenance, and operational improvement work, with recorded scope and outcomes for each contribution.",
        "technical-operations.docx",
    ),
]


def seed_starter_templates(connection) -> int:
    rows = list(connection.execute(text("SELECT id, name FROM report_templates")))
    existing = {row.name.casefold() for row in rows}
    existing_ids = {row.id for row in rows}
    count = 0
    for name, title, report_type, layout, content, filename in STARTERS:
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "careerforge:starter-report:v1:" + name))
        if name.casefold() in existing or template_id in existing_ids:
            continue
        connection.execute(
            text(
                "INSERT INTO report_templates (id, name, content, settings) VALUES (:id, :name, :content, :settings)"
            ),
            {
                "id": template_id,
                "name": name,
                "content": content,
                "settings": json.dumps(
                    {
                        "title": title,
                        "report_type": report_type,
                        "layout": layout,
                        "content": content,
                        "output_filename": filename,
                    }
                ),
            },
        )
        count += 1
    return count
