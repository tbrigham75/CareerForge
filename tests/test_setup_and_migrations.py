from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def _migration_environment(data_dir: Path) -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["CAREERFORGE_DATA_DIR"] = str(data_dir)
    environment["CAREERFORGE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    environment["PYTHONPATH"] = str(root / "backend")
    return environment


def test_fresh_migration_reaches_head_and_is_repeatable(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "CareerForgeData"
    environment = _migration_environment(data_dir)
    command = [sys.executable, "-m", "app.migrate"]

    first = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
    second = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    database = sqlite3.connect(data_dir / "data" / "careerforge.sqlite3")
    assert database.execute("select version_num from alembic_version").fetchone() == (
        "0004_workflow_settings",
    )


def test_blank_data_directory_uses_local_app_data_default(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    local_app_data = tmp_path / "LocalAppData"
    environment = os.environ.copy()
    environment["CAREERFORGE_DATA_DIR"] = ""
    environment["LOCALAPPDATA"] = str(local_app_data)
    environment["PYTHONPATH"] = str(root / "backend")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import get_settings; print(get_settings().data_dir)",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert Path(result.stdout.strip()) == local_app_data / "CareerForge"


def test_workflow_migration_preserves_legacy_labels_and_templates(tmp_path: Path):
    import json

    root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "LegacyData"
    (data_dir / "data").mkdir(parents=True)
    with sqlite3.connect(data_dir / "data" / "careerforge.sqlite3") as database:
        database.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        database.execute("INSERT INTO alembic_version VALUES ('0003_provider_retries')")
        for table in ("categories", "tags", "technologies", "skills", "competencies"):
            database.execute(
                f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, name VARCHAR(150) NOT NULL UNIQUE)"
            )
            database.executemany(
                f"INSERT INTO {table} VALUES (?, ?)", [("one", "Linux"), ("two", " linux ")]
            )
        database.execute(
            "CREATE TABLE report_templates (id VARCHAR(36) PRIMARY KEY, name VARCHAR(150) NOT NULL UNIQUE, content TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO report_templates VALUES ('template', 'Legacy', 'Keep these notes')"
        )
    result = subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        cwd=root,
        env=_migration_environment(data_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(data_dir / "data" / "careerforge.sqlite3") as database:
        assert database.execute("SELECT count(*) FROM technologies").fetchone()[0] == 2
        assert set(database.execute("SELECT id, name FROM technologies")) == {
            ("one", "Linux"),
            ("two", " linux "),
        }
        assert (
            database.execute("SELECT count(DISTINCT name_key) FROM technologies").fetchone()[0] == 2
        )
        settings = database.execute("SELECT settings FROM report_templates").fetchone()[0]
        assert json.loads(settings) == {"content": "Keep these notes"}
