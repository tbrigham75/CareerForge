from __future__ import annotations

import re

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment, Project


def token(client):
    response = client.get("/capture")
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_first_run_login_invalid_login_and_logout(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/setup"
    setup = client.get("/setup")
    csrf = re.search(r'name="csrf" value="([^"]+)"', setup.text).group(1)
    assert (
        client.post(
            "/setup",
            data={
                "csrf": csrf,
                "username": "admin",
                "password": "correct horse battery",
                "password_confirm": "correct horse battery",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    login = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    assert (
        client.post(
            "/login",
            data={"csrf": csrf, "username": "admin", "password": "wrong password"},
            follow_redirects=False,
        ).status_code
        == 401
    )
    login = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    assert (
        client.post(
            "/login",
            data={"csrf": csrf, "username": "admin", "password": "correct horse battery"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get("/dashboard").status_code == 200
    assert (
        client.post("/logout", data={"csrf": token(client)}, follow_redirects=False).status_code
        == 303
    )
    signed_out = client.get("/dashboard", follow_redirects=False)
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/login"


def test_save_raw_note_and_search(logged_in):
    response = logged_in.post(
        "/capture",
        data={
            "csrf": token(logged_in),
            "raw_note": "I updated a PowerShell script used for stale Active Directory account cleanup.",
            "sensitivity": "private_personal",
            "action_choice": "raw",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    archive = logged_in.get("/accomplishments?q=PowerShell")
    assert "PowerShell script" in archive.text


def test_capture_rejects_start_date_after_completion(logged_in):
    response = logged_in.post(
        "/capture",
        data={
            "csrf": token(logged_in),
            "title": "Invalid date order",
            "raw_note": "This record must not be saved.",
            "date_started": "2026-10-08",
            "date_completed": "2026-10-07",
            "sensitivity": "private_personal",
            "action_choice": "raw",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Start date must be on or before completion date." in response.text
    with SessionLocal() as session:
        assert (
            session.scalar(
                select(Accomplishment).where(Accomplishment.title == "Invalid date order")
            )
            is None
        )


def test_project_link_and_evidence(logged_in):
    response = logged_in.post(
        "/projects",
        data={"csrf": token(logged_in), "name": "Account hygiene", "description": "Directory work"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as session:
        project_id = session.scalar(select(Project.id).where(Project.name == "Account hygiene"))
    response = logged_in.post(
        "/capture",
        data={
            "csrf": token(logged_in),
            "raw_note": "Reviewed stale accounts.",
            "project_id": project_id,
            "sensitivity": "private_personal",
            "action_choice": "raw",
        },
        follow_redirects=False,
    )
    record_path = response.headers["location"]
    record_id = record_path.rsplit("/", 1)[-1]
    response = logged_in.post(
        f"/accomplishments/{record_id}/evidence",
        data={
            "csrf": token(logged_in),
            "reference_type": "ticket",
            "reference_value": "CHG-123",
            "notes": "Validation record",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = logged_in.get(record_path)
    assert "Account hygiene" in detail.text
    assert "CHG-123" in detail.text


def test_local_attachment_upload_and_authenticated_download(logged_in):
    response = logged_in.post(
        "/capture",
        data={
            "csrf": token(logged_in),
            "raw_note": "Captured validation evidence.",
            "sensitivity": "private_personal",
            "action_choice": "raw",
        },
        follow_redirects=False,
    )
    record_id = response.headers["location"].rsplit("/", 1)[-1]
    response = logged_in.post(
        f"/accomplishments/{record_id}/attachments",
        data={"csrf": token(logged_in), "sensitivity": "internal"},
        files={"attachment": ("validation.txt", b"validated locally", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = logged_in.get(f"/accomplishments/{record_id}")
    assert "validation.txt" in detail.text
    attachment_id = re.search(r"/attachments/([^/]+)/download", detail.text).group(1)
    download = logged_in.get(f"/attachments/{attachment_id}/download")
    assert download.content == b"validated locally"


def test_capture_with_supporting_document(logged_in):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AttachmentMetadata

    with SessionLocal() as session:
        project = Project(name="Evidence review")
        session.add(project)
        session.commit()
        project_id = project.id

    for choice in ("raw", "completed"):
        response = logged_in.post(
            "/capture",
            data={
                "csrf": token(logged_in),
                "raw_note": "Reviewed security settings.",
                "supporting_narrative": "See the assessment.",
                "sensitivity": "confidential",
                "action_choice": choice,
                "project_id": project_id,
            },
            files={"attachment": ("../assessment.txt", b"24 settings reviewed", "text/plain")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        detail = logged_in.get(response.headers["location"])
        assert "See the assessment." in detail.text
        attachment_id = re.search(r"/attachments/([^/]+)/download", detail.text).group(1)
        download = logged_in.get(f"/attachments/{attachment_id}/download")
        assert download.content == b"24 settings reviewed"
        assert "attachment;" in download.headers["content-disposition"]
        with SessionLocal() as session:
            metadata = session.scalar(
                select(AttachmentMetadata).where(AttachmentMetadata.id == attachment_id)
            )
            assert metadata.original_filename == "assessment.txt"
            assert metadata.sensitivity == "confidential"
    logged_in.cookies.clear()
    assert (
        logged_in.get(f"/attachments/{attachment_id}/download", follow_redirects=False).status_code
        == 303
    )


def test_capture_rejects_invalid_document_without_partial_record(logged_in, monkeypatch):
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.main import settings
    from app.models import Accomplishment

    monkeypatch.setattr(settings, "max_attachment_bytes", 4)
    for content, expected in ((b"", 400), (b"too large", 413)):
        response = logged_in.post(
            "/capture",
            data={
                "csrf": token(logged_in),
                "raw_note": "Keep my note",
                "metric": "24 settings",
                "action_choice": "raw",
            },
            files={"attachment": ("evidence.txt", content, "text/plain")},
        )
        assert response.status_code == expected
        assert "Keep my note" in response.text
        assert "24 settings" in response.text
        assert "Your text is preserved" in response.text
        with SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(Accomplishment)) == 0
