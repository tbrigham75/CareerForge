from __future__ import annotations

import subprocess

from test_auth_and_capture import token


def test_browser_requires_authentication_and_csrf(client, logged_in, tmp_path):
    response = logged_in.post("/files/browse", data={"kind": "odt", "csrf": "wrong"})
    assert response.status_code == 403
    logged_in.post("/logout", data={"csrf": token(logged_in)})
    response = client.post(
        "/files/browse", data={"kind": "odt", "csrf": "wrong"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_browser_filters_files_and_does_not_modify_source(logged_in, tmp_path):
    source = tmp_path / "Source document.ODT"
    source.write_bytes(b"unchanged test content")
    (tmp_path / "secret.txt").write_text("not listed")
    (tmp_path / "folder").mkdir()
    data = {"csrf": token(logged_in), "kind": "odt", "path": str(tmp_path)}
    result = logged_in.post("/files/browse", data=data).json()
    assert [item["name"] for item in result["entries"]] == ["folder", source.name]
    data.update(path=str(source), select_path="true")
    assert logged_in.post("/files/browse", data=data).json()["selected"] == str(source.resolve())
    assert source.read_bytes() == b"unchanged test content"
    data["path"] = str(tmp_path / "secret.txt")
    assert logged_in.post("/files/browse", data=data).status_code == 400


def test_browser_repository_validation_and_boundaries(logged_in, tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    folder = repo / "exports"
    folder.mkdir()
    data = {
        "csrf": token(logged_in),
        "kind": "repository",
        "path": str(repo),
        "select_path": "true",
    }
    assert logged_in.post("/files/browse", data=data).status_code == 400
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    assert logged_in.post("/files/browse", data=data).json()["selected"] == str(repo.resolve())
    data.update(kind="subdirectory", repository=str(repo), path=str(folder))
    assert logged_in.post("/files/browse", data=data).json()["selected"] == "exports"
    data.update(path=str(tmp_path), select_path="false")
    assert logged_in.post("/files/browse", data=data).status_code == 400
    data["path"] = str(repo)
    assert logged_in.post("/files/browse", data=data).json()["parent"] is None
    data.update(kind="odt", path="//server/share")
    assert logged_in.post("/files/browse", data=data).status_code == 400
    data["path"] = str(tmp_path / "missing")
    assert logged_in.post("/files/browse", data=data).status_code == 400
