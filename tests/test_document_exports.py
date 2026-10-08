from datetime import UTC, date, datetime
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from docx import Document
from odf.opendocument import load
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment, AuditEvent, Project
from app.services import document_exports
from test_auth_and_capture import token


def records():
    with SessionLocal() as session:
        record = Accomplishment(
            title="Security review",
            status="completed",
            date_started=date(2025, 1, 1),
            date_completed=date(2025, 2, 1),
            action="Reviewed configuration",
            metric="Reviewed 24 settings",
            impact="Documented service risks",
            raw_note="Private original",
            supporting_narrative="Private support",
            sensitivity="confidential",
            projects=[Project(name="CIS review")],
        )
        deleted = Accomplishment(
            title="Trash entry", status="completed", deleted_at=datetime.now(UTC)
        )
        draft = Accomplishment(title="Unfinished", status="raw_note")
        session.add_all([record, deleted, draft])
        session.commit()
        return record.id, deleted.id, draft.id


@pytest.mark.parametrize("format", ["docx", "odt", "xlsx"])
def test_download_formats_preserve_selected_content(logged_in, format, tmp_path):
    record_id, _, _ = records()
    response = logged_in.post(
        "/exports/download",
        data={
            "csrf": token(logged_in),
            "format": format,
            "scope": "all",
            "reviewed": "true",
            "title": "Tom's Brag Sheet",
            "record_ids": record_id,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == document_exports.MIME_TYPES[format]
    assert f".{format}" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(response.content)) as archive:
        xml = "\n".join(
            archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml")
        )
    for value in [
        "Security review",
        "Reviewed 24 settings",
        "Documented service risks",
        "CIS review",
    ]:
        assert value in xml
    assert (
        "Private original" not in xml and "Private support" not in xml and "Trash entry" not in xml
    )
    if format == "docx":
        assert len(Document(BytesIO(response.content)).tables) == 1
    elif format == "odt":
        assert load(BytesIO(response.content)).mimetype == document_exports.MIME_TYPES[format]
    else:
        with ZipFile(BytesIO(response.content)) as archive:
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            assert sheet.find("s:autoFilter", ns) is not None
            assert sheet.find('.//s:c[@r="B5"]/s:v', ns) is not None
    with SessionLocal() as session:
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "document.exported")
        )
        assert session.get(Accomplishment, record_id).raw_note == "Private original"
    # Files are internal QA fixtures, never user data or committed outputs.
    (tmp_path / f"brag-sheet.{format}").write_bytes(response.content)


def test_scope_confirmation_auth_and_notes(logged_in):
    record_id, deleted_id, draft_id = records()
    csrf = token(logged_in)
    data = {
        "csrf": csrf,
        "format": "docx",
        "scope": "all",
        "reviewed": "true",
        "record_ids": record_id,
    }
    for override in [
        {"csrf": "bad"},
        {"reviewed": "false"},
        {"format": "pdf"},
        {"record_ids": deleted_id},
        {"record_ids": draft_id},
        {"record_ids": "missing"},
        {"record_ids": ""},
        {"scope": "invalid"},
        {"project_id": "missing"},
    ]:
        assert logged_in.post("/exports/download", data={**data, **override}).status_code in {
            400,
            403,
        }
    response = logged_in.post("/exports/download", data={**data, "include_notes": "true"})
    with ZipFile(BytesIO(response.content)) as archive:
        assert "Private original" in archive.read("word/document.xml").decode()
    assert "Repository path" not in logged_in.get("/exports?scope=all").text
    assert "Repository path" in logged_in.get("/git-sync").text
    assert logged_in.post("/exports/dry-run", data={"csrf": csrf}).status_code == 200
    assert logged_in.post("/git-sync/dry-run", data={"csrf": csrf}).status_code == 200
    logged_in.cookies.clear()
    assert logged_in.get("/exports", follow_redirects=False).status_code == 303
    assert logged_in.get("/git-sync", follow_redirects=False).status_code == 303


def test_excel_treats_formula_like_content_as_literal_text():
    record = Accomplishment(
        title='=HYPERLINK("https://example.com")',
        status="completed",
        action="=1+1",
        metric="+cmd",
        impact="@SUM(A1)",
        projects=[],
        sensitivity="internal",
    )
    content = document_exports.excel_document([record], "=1+1", False)
    with ZipFile(BytesIO(content)) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode()
        assert "<f>" not in xml and "<hyperlinks>" not in xml
        assert not any("externalLink" in name for name in archive.namelist())
        assert "=1+1" in archive.read("xl/sharedStrings.xml").decode()
