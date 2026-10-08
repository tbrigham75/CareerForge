from datetime import date

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Accomplishment, Project, Tag
from test_auth_and_capture import token


def test_completed_capture_requires_real_project_and_preserves_fields(logged_in):
    data = {
        "csrf": token(logged_in),
        "raw_note": "Keep this note",
        "title": "Keep this title",
        "action_choice": "completed",
        "tags": "Must not persist",
        "date_started": "2026-10-01",
        "date_completed": "2026-10-05",
    }
    response = logged_in.post("/capture", data=data)
    assert response.status_code == 400
    assert "Select a project" in response.text
    assert "Keep this note" in response.text and "2026-10-01" in response.text
    response = logged_in.post("/capture", data={**data, "project_id": "missing"})
    assert response.status_code == 400
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Accomplishment)) == 0
        assert session.scalar(select(func.count()).select_from(Tag)) == 0
        project = Project(name="Security review")
        session.add(project)
        session.commit()
        project_id = project.id
    assert logged_in.get("/capture/projects").json()["projects"] == [
        {"id": project_id, "name": "Security review"}
    ]
    response = logged_in.post(
        "/capture", data={**data, "project_id": project_id}, follow_redirects=False
    )
    assert response.status_code == 303
    with SessionLocal() as session:
        record = session.get(Accomplishment, response.headers["location"].rsplit("/", 1)[-1])
        assert [item.id for item in record.projects] == [project_id]
        assert record.date_started == date(2026, 10, 1)
        assert record.date_completed == date(2026, 10, 5)


def test_raw_note_project_optional_and_date_defaults_rendered(logged_in, client):
    page = logged_in.get("/capture")
    assert f'name="date_started" value="{date.today().isoformat()}"' in page.text
    assert f'name="date_completed" value="{date.today().isoformat()}"' in page.text
    response = logged_in.post(
        "/capture",
        data={"csrf": token(logged_in), "raw_note": "Quick note", "action_choice": "raw"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    logged_in.cookies.clear()
    assert client.get("/capture/projects", follow_redirects=False).status_code == 303
