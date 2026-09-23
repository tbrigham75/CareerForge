from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "CareerForge" if local_app_data else Path.home() / ".careerforge"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CAREERFORGE_", extra="ignore")

    data_dir: Path = _default_data_dir()
    host: str = "127.0.0.1"
    port: int = 8000
    session_timeout_minutes: int = 60
    cookie_secure: bool = False
    allow_private_http: bool = True
    max_ai_response_bytes: int = 1_048_576
    max_attachment_bytes: int = 25 * 1024 * 1024
    encryption_key: str = ""

    @field_validator("data_dir", mode="before")
    @classmethod
    def empty_data_dir_uses_windows_default(cls, value: object) -> object:
        """Treat an empty value in a copied .env file as unset, not as the working directory."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return _default_data_dir()
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "data" / "careerforge.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    def ensure_directories(self) -> None:
        for name in (
            "data",
            "attachments",
            "exports",
            "reports",
            "git-worktrees",
            "backups",
            "logs",
            "templates",
            "secrets",
            "temp",
        ):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
