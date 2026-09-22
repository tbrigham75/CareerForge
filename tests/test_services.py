from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.db import SessionLocal
from app.schemas import AccomplishmentInput
from app.security import decrypt_secret, encrypt_secret
from app.services.accomplishments import archive, create, update
from app.services.ai import ProviderSafetyError, classify_and_validate_url
from app.services.backup import BackupError, create_backup, validate_backup_archive
from app.services.exporter import export_markdown
from app.services.reports import generate_docx


def test_secret_round_trip_and_endpoint_policy():
    assert decrypt_secret(encrypt_secret("super-secret")) == "super-secret"
    assert classify_and_validate_url("http://localhost:11434") == "local"
    with pytest.raises(ProviderSafetyError):
        classify_and_validate_url("http://example.com")
    with pytest.raises(ProviderSafetyError):
        classify_and_validate_url("http://169.254.169.254")


def test_revisions_archive_report_and_export(tmp_path: Path):
    with SessionLocal() as session:
        record = create(
            session,
            AccomplishmentInput(
                title="Patch servers",
                raw_note="Patched servers",
                action="Patched four servers",
                metric="Four servers",
                impact="[Confirm impact]",
                github_export=True,
                sensitivity="internal",
                status="completed",
                approval_status="approved",
            ),
        )
        record = update(
            session,
            record,
            AccomplishmentInput(
                title="Patch servers",
                raw_note="Patched servers",
                action="Patched four servers",
                metric="Four servers",
                impact="[Confirm impact]",
                github_export=True,
                sensitivity="internal",
                status="completed",
                approval_status="approved",
            ),
        )
        archive(session, record, True)
        assert len(record.revisions) == 3
        archive(session, record, False)
        report = generate_docx(session, "Test report", [record])
        assert Path(report.output_path).is_file()
        manifest = export_markdown(session, tmp_path, dry_run=False)
        assert len(manifest["files"]) == 1
        assert (tmp_path / manifest["files"][0]).read_text(encoding="utf-8").startswith("---")


def test_backup_creation_and_unsafe_member_rejection(tmp_path: Path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "careerforge.sqlite3").write_text("test", encoding="utf-8")
    backup = create_backup(tmp_path)
    assert backup.is_file()
    assert "data/careerforge.sqlite3" in validate_backup_archive(backup)
    unsafe = tmp_path / "unsafe.zip"
    with ZipFile(unsafe, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("../outside.txt", "no")
    with pytest.raises(BackupError):
        validate_backup_archive(unsafe)
