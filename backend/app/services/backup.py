from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile


class BackupError(ValueError):
    pass


def create_backup(data_dir: Path) -> Path:
    """Create a portable archive without recursively including older backups."""
    if not data_dir.is_dir():
        raise BackupError("CareerForge data directory does not exist.")
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_dir / f"CareerForge-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for path in data_dir.rglob("*"):
            if path.is_file() and backup_dir not in path.parents:
                bundle.write(path, path.relative_to(data_dir))
    return archive


def validate_backup_archive(archive: Path) -> list[str]:
    """Return archive members only when every path is safe to extract."""
    try:
        with ZipFile(archive) as bundle:
            names = bundle.namelist()
    except (BadZipFile, OSError) as exc:
        raise BackupError("Backup archive cannot be opened.") from exc
    for name in names:
        member = Path(name)
        if member.is_absolute() or ".." in member.parts:
            raise BackupError("Backup archive contains an unsafe path.")
    return names
