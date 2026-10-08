from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Accomplishment,
    AccomplishmentRevision,
    AIDraft,
    AttachmentMetadata,
    EvidenceReference,
    PendingFileDeletion,
    Project,
    Report,
    ReportItem,
    Tag,
)
from app.services import accomplishments, trash
from test_auth_and_capture import token


def seed(archived=False, age=0):
    with SessionLocal() as session:
        record = Accomplishment(
            title="Recover me",
            is_archived=archived,
            deleted_at=datetime.now(UTC) - timedelta(days=age),
        )
        project = Project(name="Keep project")
        record.projects.append(project)
        session.add_all([record, Tag(name="Keep tag")])
        session.flush()
        session.add_all(
            [
                EvidenceReference(accomplishment_id=record.id, reference_value="ticket"),
                AccomplishmentRevision(
                    accomplishment_id=record.id, revision_number=1, snapshot={"title": "Recover me"}
                ),
                AIDraft(accomplishment_id=record.id, content={"action": "Draft"}),
            ]
        )
        path = get_settings().data_dir / "attachments" / record.id / "proof.txt"
        path.parent.mkdir(parents=True)
        path.write_text("Synthetic test document")
        attachment = AttachmentMetadata(
            accomplishment_id=record.id,
            stored_path=str(path),
            original_filename="proof.txt",
            content_hash="test",
        )
        report = Report(title="Historical report")
        session.add_all([attachment, report])
        session.flush()
        session.add(
            ReportItem(
                report_id=report.id,
                accomplishment_id=record.id,
                position=1,
                source_snapshot={"title": "Recover me"},
            )
        )
        session.commit()
        return record.id, attachment.id, path


def test_restore_preserves_archive_relationships_and_documents(logged_in):
    record_id, attachment_id, path = seed(archived=True)
    csrf = token(logged_in)
    assert "Recover me" in logged_in.get("/trash").text
    assert logged_in.get(f"/accomplishments/{record_id}").status_code == 404
    assert logged_in.get(f"/attachments/{attachment_id}/download").status_code == 404
    assert logged_in.post(f"/trash/{record_id}/restore", data={"csrf": "bad"}).status_code == 403
    response = logged_in.post(f"/trash/{record_id}/restore", data={"csrf": csrf})
    assert response.status_code == 200
    assert "Trash is empty" in response.text
    with SessionLocal() as session:
        record = session.get(Accomplishment, record_id)
        assert record.deleted_at is None and record.is_archived
        assert len(record.projects) == len(record.revisions) == len(record.evidence_references) == 1
        assert not accomplishments.search(session)
        assert len(accomplishments.search(session, include_archived=True)) == 1
    assert path.exists()
    assert logged_in.get(f"/attachments/{attachment_id}/download").status_code == 200
    assert (
        logged_in.post(
            f"/trash/{record_id}/delete", data={"csrf": csrf, "confirmation": "DELETE"}
        ).status_code
        == 404
    )


def test_purge_removes_dependents_but_keeps_reports_projects_taxonomy(logged_in):
    record_id, _, path = seed()
    csrf = token(logged_in)
    assert logged_in.post(f"/trash/{record_id}/delete", data={"csrf": csrf}).status_code == 400
    assert path.exists()
    assert (
        logged_in.post(
            f"/trash/{record_id}/delete", data={"csrf": csrf, "confirmation": "DELETE"}
        ).status_code
        == 200
    )
    assert not path.exists()
    with SessionLocal() as session:
        assert session.get(Accomplishment, record_id) is None
        for model in [
            AccomplishmentRevision,
            EvidenceReference,
            AIDraft,
            AttachmentMetadata,
            PendingFileDeletion,
        ]:
            assert session.scalar(select(model)) is None
        item = session.scalar(select(ReportItem))
        assert item.accomplishment_id is None and item.source_snapshot["title"] == "Recover me"
        assert session.scalar(select(Project)) and session.scalar(select(Tag))


def test_maintenance_retention_and_locked_file_retry(monkeypatch):
    record_id, _, path = seed(age=31)
    real_unlink = Path.unlink

    def locked(self, *args, **kwargs):
        if self == path:
            raise PermissionError("Synthetic locked file")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    with SessionLocal() as session:
        recent = Accomplishment(title="Recent", deleted_at=datetime.now(UTC))
        archived = Accomplishment(title="Archived", is_archived=True)
        session.add_all([recent, archived])
        session.commit()
        trash.maintenance(session)
        assert session.get(Accomplishment, record_id) is None
        assert session.get(Accomplishment, recent.id) and session.get(Accomplishment, archived.id)
        assert "locked file" in session.scalar(select(PendingFileDeletion)).last_error
        monkeypatch.setattr(Path, "unlink", real_unlink)
        trash.maintenance(session)
        assert not path.exists()
        assert session.scalar(select(PendingFileDeletion)) is None


def test_unsafe_path_never_deleted_and_empty_trash_requires_confirmation(logged_in, tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("Keep")
    with SessionLocal() as session:
        session.add(PendingFileDeletion(stored_path=str(outside)))
        session.commit()
        trash.cleanup_files(session)
        assert outside.exists()
        assert "Unsafe" in session.scalar(select(PendingFileDeletion)).last_error
    csrf = token(logged_in)
    assert logged_in.post("/trash/empty", data={"csrf": csrf}).status_code == 400
    seed()
    assert (
        logged_in.post(
            "/trash/empty", data={"csrf": csrf, "confirmation": "EMPTY TRASH"}
        ).status_code
        == 200
    )
    with SessionLocal() as session:
        assert session.scalar(select(Accomplishment)) is None
    logged_in.cookies.clear()
    assert logged_in.get("/trash", follow_redirects=False).status_code == 303


def test_move_to_trash_restores_active_record(logged_in):
    csrf = token(logged_in)
    with SessionLocal() as session:
        record = Accomplishment(title="Active")
        session.add(record)
        session.commit()
        record_id = record.id
    assert (
        logged_in.post(f"/accomplishments/{record_id}/delete", data={"csrf": csrf}).status_code
        == 200
    )
    assert logged_in.post(f"/trash/{record_id}/restore", data={"csrf": csrf}).status_code == 200
    assert logged_in.get(f"/accomplishments/{record_id}").status_code == 200
