"""Conservative, explicit SQLite diagnostics and compaction."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from app.config import get_settings
from app.services.trash import lock


def storage_summary() -> dict[str, int]:
    settings = get_settings()
    with closing(sqlite3.connect(settings.database_path, timeout=5)) as connection:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        free = connection.execute("PRAGMA freelist_count").fetchone()[0]
    root = (settings.data_dir / "attachments").resolve()
    attachment_bytes = 0
    unreadable = 0
    for path in root.rglob("*"):
        try:
            if not path.is_symlink() and root in path.resolve().parents and path.is_file():
                attachment_bytes += path.stat().st_size
        except OSError:
            unreadable += 1
    return {
        "database_bytes": pages * page_size,
        "reusable_bytes": free * page_size,
        "attachment_bytes": attachment_bytes,
        "unreadable_files": unreadable,
    }


def check_health() -> dict[str, object]:
    with closing(sqlite3.connect(get_settings().database_path, timeout=5)) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        relationships = list(connection.execute("PRAGMA foreign_key_check"))
    return {
        "healthy": integrity == ["ok"] and not relationships,
        "integrity": integrity,
        "relationship_issues": len(relationships),
    }


def compact_database() -> Path:
    """Online SQLite backup first; VACUUM either succeeds or leaves the DB intact.

    This is a database-only snapshot, not an attachment/full application backup.
    SQLite handles concurrent app traffic with its own database locks.
    """
    settings = get_settings()
    with lock:
        health = check_health()
        if not health["healthy"]:
            raise ValueError("Health checks found issues. Compaction was not attempted.")
        backup = (
            settings.data_dir
            / "backups"
            / (f"Database-before-compact-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.sqlite3")
        )
        with closing(sqlite3.connect(settings.database_path, timeout=5)) as connection:
            with closing(sqlite3.connect(backup)) as destination:
                deadline = monotonic() + 30

                def check_timeout(status: int, remaining: int, total: int) -> None:
                    if monotonic() > deadline:
                        raise TimeoutError("Database backup timed out; compaction not attempted.")

                connection.backup(destination, pages=128, progress=check_timeout)
                if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Backup verification failed. Compaction was not attempted.")
            connection.execute("VACUUM")
        return backup
