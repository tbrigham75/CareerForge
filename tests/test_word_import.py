from docx import Document
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment
from test_auth_and_capture import token


def test_word_import_tables_duplicates_and_source_preservation(logged_in, tmp_path):

    source = tmp_path / "work.DOCX"

    document = Document()

    document.add_paragraph("Automated the monthly inventory collection process.")

    document.add_table(rows=1, cols=1).cell(0, 0).text = "Reduced manual collection effort by three hours."

    document.save(source)

    original = source.read_bytes()

    data = {"csrf": token(logged_in), "source_path": str(source), "confirmation": "IMPORT"}

    response = logged_in.post("/imports/document", data=data)

    assert response.status_code == 200

    assert "records added: 2" in response.text

    assert "skipped_duplicate" in logged_in.post("/imports/document", data=data).text

    assert source.read_bytes() == original

    with SessionLocal() as session:

        records = list(session.scalars(select(Accomplishment)))

        assert len(records) == 2

        assert all(r.source_origin == "imported_docx" and r.status == "raw_note" for r in records)

    result = logged_in.post("/files/browse", data={"csrf": token(logged_in), "kind": "odt", "path": str(source), "select_path": "true"})

    assert result.json()["selected"] == str(source.resolve())





def test_invalid_word_document_returns_helpful_error(logged_in, tmp_path):

    source = tmp_path / "broken.docx"

    source.write_text("not a Word document")

    response = logged_in.post("/imports/document", data={"csrf": token(logged_in), "source_path": str(source), "confirmation": "IMPORT"})

    assert response.status_code == 400

    assert "valid, unencrypted" in response.text





def test_structured_word_rows_keep_fields_and_missing_values():

    from app.services.importer import word_entries

    document = Document()

    table = document.add_table(rows=1, cols=3)

    for cell, value in zip(table.rows[0].cells, ['Action “I did this”', 'Metric “How many”', 'Impact “Why mattered”'], strict=True):

        cell.text = value

    for values in [('Patched servers', '30 servers', 'Met compliance'), ('Improved backups', '', 'Reduced risk')]:

        for cell, value in zip(table.add_row().cells, values, strict=True):

            cell.text = value

    entries = word_entries(document)

    assert len(entries) == 2

    assert (entries[0].action, entries[0].metric, entries[0].impact) == ('Patched servers', '30 servers', 'Met compliance')

    assert entries[1].metric == ''

    assert entries[1].impact == 'Reduced risk'





def test_labeled_word_sections_and_vertical_table():

    from app.services.importer import word_entries

    document = Document()

    for line in ['Action:', 'Patched servers', 'Metrics: 30 servers', 'Impact: Met compliance']:

        document.add_paragraph(line)

    table = document.add_table(rows=0, cols=2)

    for values in [('Action', 'Improved backups'), ('Metrix', '5 systems'), ('Impact', 'Reduced risk')]:

        for cell, value in zip(table.add_row().cells, values, strict=True):

            cell.text = value

    entries = word_entries(document)

    assert len(entries) == 2

    assert entries[0].action == 'Patched servers'

    assert entries[0].metric == '30 servers'

    assert entries[1].metric == '5 systems'



def test_legacy_word_reimport_replaces_only_untouched_fragments(tmp_path):
    from app.models import ImportRun
    from app.schemas import AccomplishmentInput
    from app.services.accomplishments import create
    from app.services.importer import file_hash, import_document
    source = tmp_path / "legacy.docx"
    document = Document()
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ['Action', 'Metric', 'Impact'], strict=True):
        cell.text = value
    values = ['Patched every application server', '30 servers within three days', 'Resolved all known vulnerabilities']
    for cell, value in zip(table.add_row().cells, values, strict=True):
        cell.text = value
    document.save(source)
    with SessionLocal() as session:
        fragments = []
        for value in values:
            record = create(session, AccomplishmentInput(raw_note=value, status='raw_note', sensitivity='internal'))
            record.source_path = str(source.resolve())
            record.source_origin = 'imported_docx'
            fragments.append(record)
        session.add(ImportRun(source_path=str(source), filename=source.name, source_hash=file_hash(source), status='completed', imported_count=3))
        session.commit()
        moved_source = tmp_path / "moved.docx"
        moved_source.write_bytes(source.read_bytes())
        assert import_document(session, moved_source).imported_count == 1
        assert all(record.deleted_at for record in fragments)
        active = list(session.scalars(select(Accomplishment).where(Accomplishment.deleted_at.is_(None))))
        assert len(active) == 1
        assert (active[0].action, active[0].metric, active[0].impact) == tuple(values)
        assert import_document(session, source).status == 'skipped_duplicate'


def test_reimport_adds_new_rows_and_preserves_edited_raw_note(logged_in, tmp_path):
    source = tmp_path / "evolving.docx"
    document = Document()
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ["Action", "Metric", "Impact"], strict=True):
        cell.text = value
    for cell, value in zip(table.add_row().cells, ["Built a storage tool", "Three systems", "Supported capacity review"], strict=True):
        cell.text = value
    document.save(source)
    data = {"csrf": token(logged_in), "source_path": str(source), "confirmation": "IMPORT"}
    assert "records added: 1" in logged_in.post("/imports/document", data=data).text
    with SessionLocal() as session:
        record = session.scalar(select(Accomplishment))
        rid, fingerprint = record.id, record.source_hash
    edited = "Built a storage tool to investigate PBS capacity and help plan cleanup."
    response = logged_in.post(f"/accomplishments/{rid}/edit", data={
        "csrf": token(logged_in), "title": "Storage review", "raw_note": edited,
        "action": "Built a storage tool", "metric": "Three systems", "impact": "Supported capacity review",
        "status": "raw_note", "sensitivity": "internal", "approval_status": "draft",
    })
    assert response.status_code == 200
    assert "skipped_duplicate" in logged_in.post("/imports/document", data=data).text
    for cell, value in zip(table.add_row().cells, ["Reviewed backup jobs", "Five jobs", "Identified failed backups"], strict=True):
        cell.text = value
    document.save(source)
    assert "records added: 1" in logged_in.post("/imports/document", data=data).text
    with SessionLocal() as session:
        records = list(session.scalars(select(Accomplishment)))
        assert len(records) == 2
        record = session.get(Accomplishment, rid)
        assert record.raw_note == edited
        assert record.source_hash == fingerprint
        assert len(record.revisions) == 2
        assert record.revisions[0].snapshot["raw_note"] != edited
