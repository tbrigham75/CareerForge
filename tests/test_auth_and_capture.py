from __future__ import annotations

import re

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Project


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
