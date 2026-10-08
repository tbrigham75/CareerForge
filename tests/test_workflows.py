from io import BytesIO

from docx import Document
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Accomplishment, Category, ReportTemplate, SystemService, Tag, Technology
from test_auth_and_capture import token


def capture(client, **values):
    from app.models import Project

    with SessionLocal() as session:
        project = session.scalar(select(Project))
        if project is None:
            project = Project(name="Test project")
            session.add(project)
            session.commit()
        project_id = project.id
    data = {
        "csrf": token(client),
        "raw_note": "Reviewed settings",
        "action_choice": "completed",
        "project_id": project_id,
        **values,
    }
    return client.post("/capture", data=data, follow_redirects=False)


def test_labels_register_on_create_update_and_remain_reusable(logged_in):
    first = capture(
        logged_in,
        systems=" Service Desk, service desk, , VPN ",
        technologies=" Linux,linux ",
        tags=" Review , REVIEW",
        categories="Security",
    )
    assert first.status_code == 303
    first_id = first.headers["location"].rsplit("/", 1)[-1]
    second = capture(
        logged_in,
        systems="service desk",
        technologies="LINUX",
        tags="review",
        categories=" security ",
    )
    assert second.status_code == 303
    with SessionLocal() as session:
        for model, count in ((SystemService, 2), (Technology, 1), (Tag, 1), (Category, 1)):
            assert session.scalar(select(func.count()).select_from(model)) == count
        original = session.get(Accomplishment, first_id)
        assert original.systems == ["Service Desk", "VPN"]
        assert original.sensitivity == "private_personal"
    response = logged_in.post(
        "/taxonomy", data={"csrf": token(logged_in), "kind": "tag", "name": "Unassigned"}
    )
    assert response.status_code == 200
    with SessionLocal() as session:
        assert all(
            "Unassigned" not in record.tags for record in session.scalars(select(Accomplishment))
        )
    response = logged_in.post(
        f"/accomplishments/{first_id}/edit",
        data={
            "csrf": token(logged_in),
            "title": "Edited",
            "raw_note": "Reviewed",
            "technologies": "Python",
            "sensitivity": "do_not_sync",
        },
    )
    assert response.status_code == 200
    with SessionLocal() as session:
        assert session.get(Accomplishment, first_id).tags == []
        assert session.scalar(select(func.count()).select_from(Tag)) == 2
        assert session.scalar(select(func.count()).select_from(Technology)) == 2
    suggestions = logged_in.get("/taxonomy/suggestions").json()
    assert suggestions["systems"] == ["Service Desk", "VPN"]
    assert "Python" in suggestions["technologies"]


def test_failed_saves_do_not_register_labels(logged_in, monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "max_attachment_bytes", 4)
    response = logged_in.post(
        "/capture",
        data={"csrf": token(logged_in), "raw_note": "Keep my work", "tags": "Should not exist"},
        files={"attachment": ("large.txt", b"12345", "text/plain")},
    )
    assert response.status_code == 413
    response = capture(
        logged_in, tags="Invalid date label", date_started="2026-10-09", date_completed="2026-10-01"
    )
    assert response.status_code == 400
    response = capture(logged_in, tags="Invalid privacy label", sensitivity="invented")
    assert response.status_code == 400
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Tag)) == 0
        assert session.scalar(select(func.count()).select_from(Accomplishment)) == 0


def test_report_templates_and_selected_output(logged_in):
    first = capture(logged_in, title="Include this", date_completed="2026-10-08")
    second = capture(logged_in, title="Exclude this", date_completed="2026-10-08")
    ids = [result.headers["location"].rsplit("/", 1)[-1] for result in (first, second)]
    page = logged_in.get("/reports")
    assert page.text.count('name="record_ids"') == 2
    assert page.text.count("checked> <strong>") == 2
    headers = {"Accept": "application/json"}
    template = logged_in.post(
        "/reports/templates",
        headers=headers,
        data={
            "csrf": token(logged_in),
            "name": "Monthly",
            "title": "Team report",
            "content": "Original notes",
            "report_type": "monthly",
            "output_filename": "team.docx",
            "record_ids": ids,
        },
    ).json()
    template_id = template["id"]
    assert "record_ids" not in template["settings"]
    updated = logged_in.post(
        f"/reports/templates/{template_id}/update",
        headers=headers,
        data={
            "csrf": token(logged_in),
            "name": "Monthly revised",
            "content": "Revised notes",
            "title": "Team report",
            "report_type": "monthly",
            "output_filename": "team.docx",
        },
    )
    assert updated.status_code == 200
    assert "Monthly revised" in logged_in.get("/reports").text
    response = logged_in.post(
        "/reports",
        data={
            "csrf": token(logged_in),
            "title": "My edited report",
            "content": "My edited notes",
            "report_type": "monthly",
            "output_filename": "my-report.docx",
            "template_id": template_id,
            "record_ids": [ids[0]],
        },
    )
    assert response.status_code == 200
    assert "my-report.docx" in response.headers["content-disposition"]
    text = "\n".join(p.text for p in Document(BytesIO(response.content)).paragraphs)
    assert "Include this" in text and "Exclude this" not in text
    assert "My edited notes" in text and "My edited report" in text
    empty = logged_in.post(
        "/reports",
        data={"csrf": token(logged_in), "title": "Keep this title", "content": "Keep these notes"},
    )
    assert empty.status_code == 400
    assert "Keep this title" in empty.text and "Keep these notes" in empty.text
    assert "checked> <strong>" not in empty.text
    assert "Select at least one accomplishment" in empty.text
    invalid = logged_in.post(
        "/reports",
        data={
            "csrf": token(logged_in),
            "title": "Valid",
            "record_ids": [ids[0]],
            "date_from": "2027-01-01",
        },
    )
    assert invalid.status_code == 400
    assert (
        logged_in.post(f"/reports/templates/{template_id}/delete", data={"csrf": "bad"}).status_code
        == 403
    )
    assert (
        logged_in.post(
            f"/reports/templates/{template_id}/delete", data={"csrf": token(logged_in)}
        ).status_code
        == 200
    )
    with SessionLocal() as session:
        assert session.get(ReportTemplate, template_id) is None
    assert "Monthly revised" not in logged_in.get("/reports").text


def test_backups_label_and_legacy_url(logged_in):
    response = logged_in.get("/operations")
    assert "<h1>Backups</h1>" in response.text
    assert ">Operations<" not in response.text
    response = logged_in.post(
        "/operations/backup", data={"csrf": token(logged_in), "confirmation": "BACKUP"}
    )
    assert response.status_code == 200
