from fastapi.testclient import TestClient

from careerforge.config import Settings
from careerforge.main import create_app


def make_client(tmp_path):
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'test.db'}", session_secret="test-secret", secure_cookies=False)
    return TestClient(create_app(settings))


def setup(client):
    response = client.post("/api/setup", json={"username": "admin", "password": "a-safe-test-password"})
    assert response.status_code == 201
    return response.json()["csrf_token"]


def test_local_setup_is_one_time_and_password_is_not_returned(tmp_path):
    with make_client(tmp_path) as client:
        csrf = setup(client)
        assert csrf
        assert "password" not in client.post("/api/login", json={"username": "admin", "password": "a-safe-test-password"}).text
        assert client.post("/api/setup", json={"username": "other", "password": "a-safe-test-password"}).status_code == 409


def test_raw_note_crud_preserves_revision_history(tmp_path):
    with make_client(tmp_path) as client:
        csrf = setup(client)
        headers = {"X-CSRF-Token": csrf}
        created = client.post("/api/accomplishments", headers=headers, json={"raw_note": "Fixed the backup job."})
        assert created.status_code == 201
        record = created.json()
        assert record["status"] == "raw_note"
        updated = client.put(f"/api/accomplishments/{record['id']}", headers=headers, json={"title": "Restored backup processing", "raw_note": "Fixed the backup job.", "action": "Investigated and corrected the backup job configuration."})
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        assert len(client.get("/api/accomplishments", headers=headers).json()) == 1
        assert client.delete(f"/api/accomplishments/{record['id']}", headers=headers).status_code == 204
        assert client.get("/api/accomplishments", headers=headers).json() == []


def test_mutations_require_csrf(tmp_path):
    with make_client(tmp_path) as client:
        setup(client)
        assert client.post("/api/accomplishments", json={"raw_note": "I did this"}).status_code == 403


def test_browser_ui_is_served(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "CareerForge" in response.text
        assert "I Did This" in response.text
