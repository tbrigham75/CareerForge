from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    session_secret: str
    secure_cookies: bool


def load_settings() -> Settings:
    default_data_dir = (
        Path(os.environ["LOCALAPPDATA"]) / "CareerForge"
        if os.name == "nt" and os.getenv("LOCALAPPDATA")
        else Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "careerforge"
    )
    data_dir = Path(os.getenv("CAREERFORGE_DATA_DIR", str(default_data_dir))).resolve()
    database_url = os.getenv("CAREERFORGE_DATABASE_URL", f"sqlite:///{data_dir / 'careerforge.db'}")
    return Settings(
        data_dir=data_dir,
        database_url=database_url,
        session_secret=os.getenv("CAREERFORGE_SESSION_SECRET", "development-only-change-before-lan-use"),
        secure_cookies=os.getenv("CAREERFORGE_SECURE_COOKIES", "false").lower() == "true",
    )
