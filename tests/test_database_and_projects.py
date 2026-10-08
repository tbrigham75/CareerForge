import sqlite3

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Accomplishment, AuditEvent, Project
from app.services import database_maintenance
from test_auth_and_capture import token


def test_project_edit_preserves_links_and_validates(logged_in):
    with SessionLocal() as session:
        project = Project(name="Original")
        record = Accomplishment(title="Linked", projects=[project])
        session.add_all([record, Project(name="Other")])
        session.commit()
        project_id, record_id = project.id, record.id
    url = f"/projects/{project_id}/edit"
    assert f'href="{url}"' in logged_in.get("/projects").text
    assert logged_in.get(url).status_code == 200
    csrf = token(logged_in)
    data = {"csrf": csrf, "name": "Renamed", "description": "Added description"}
    assert logged_in.post(url, data={**data, "csrf": "wrong"}).status_code == 403
    assert logged_in.post(url, data={**data, "name": " "}).status_code == 400
    response = logged_in.post(url, data={**data, "name": "other"})
    assert response.status_code == 409 and "Added description" in response.text
    assert logged_in.post(url, data=data).status_code == 200
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        assert project.name == "Renamed" and project.description == "Added description"
        assert session.get(Accomplishment, record_id).projects[0].id == project_id
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "project.updated"))
    assert logged_in.get("/projects/missing/edit").status_code == 404
    assert logged_in.post("/projects/missing/edit", data=data).status_code == 404
    logged_in.cookies.clear()
    assert logged_in.get(url, follow_redirects=False).status_code == 303


def test_database_actions_backup_and_data_preservation(logged_in):
    with SessionLocal() as session:
        session.add(Project(name="Keep me"))
        session.commit()
    assert logged_in.get("/database").status_code == 200
    csrf = token(logged_in)
    assert logged_in.post("/database/check", data={"csrf": "bad"}).status_code == 403
    response = logged_in.post("/database/check", data={"csrf": csrf})
    assert response.status_code == 200 and "Health checks passed" in response.text
    assert logged_in.post("/database/compact", data={"csrf": csrf}).status_code == 400
    response = logged_in.post("/database/compact", data={"csrf": csrf, "confirmation": "COMPACT"})
    assert response.status_code == 200 and "Database compacted" in response.text
    backup = max((get_settings().data_dir / "backups").glob("Database-before-compact-*.sqlite3"))
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("SELECT name FROM projects").fetchone()[0] == "Keep me"
    with SessionLocal() as session:
        assert session.scalar(select(Project)).name == "Keep me"
    assert logged_in.post("/database/cleanup", data={"csrf": csrf}).status_code == 200
    assert logged_in.post("/database/invalid", data={"csrf": csrf}).status_code == 404
    logged_in.cookies.clear()
    assert logged_in.get("/database", follow_redirects=False).status_code == 303


def test_failed_health_blocks_compaction_and_busy_error_is_friendly(logged_in, monkeypatch):
    csrf = token(logged_in)
    monkeypatch.setattr(database_maintenance, "check_health", lambda: {"healthy": False})
    response = logged_in.post("/database/compact", data={"csrf": csrf, "confirmation": "COMPACT"})
    assert response.status_code == 503 and "Maintenance could not finish" in response.text

    def busy():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(database_maintenance, "compact_database", busy)
    assert (
        logged_in.post(
            "/database/compact", data={"csrf": csrf, "confirmation": "COMPACT"}
        ).status_code
        == 503
    )
