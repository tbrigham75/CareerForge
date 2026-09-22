from __future__ import annotations

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["CAREERFORGE_DATA_DIR"] = tempfile.mkdtemp(prefix="careerforge-tests-")
os.environ["CAREERFORGE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def csrf(client: TestClient) -> str:
    response = client.get("/setup", follow_redirects=False)
    if response.status_code == 303:
        response = client.get("/login")
    # Session is a signed cookie; a valid token is available from the rendered form.
    import re

    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


@pytest.fixture
def logged_in(client: TestClient) -> TestClient:
    token = csrf(client)
    response = client.post(
        "/setup",
        data={
            "csrf": token,
            "username": "admin",
            "password": "correct horse battery",
            "password_confirm": "correct horse battery",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf": token, "username": "admin", "password": "correct horse battery"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client
