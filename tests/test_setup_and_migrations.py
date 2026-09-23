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
        "0003_provider_retries",
    )


def test_blank_data_directory_uses_local_app_data_default(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    local_app_data = tmp_path / "LocalAppData"
    environment = os.environ.copy()
    environment["CAREERFORGE_DATA_DIR"] = ""
    environment["LOCALAPPDATA"] = str(local_app_data)
    environment["PYTHONPATH"] = str(root / "backend")

    result = subprocess.run(
        [sys.executable, "-c", "from app.config import get_settings; print(get_settings().data_dir)"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert Path(result.stdout.strip()) == local_app_data / "CareerForge"
