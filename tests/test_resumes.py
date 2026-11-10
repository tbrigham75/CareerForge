"""Prepared regression checks; run against an isolated test environment."""
from pathlib import Path

import pytest
from docx import Document

from app.services.resumes import append_bullets, read_document, validate_placement


def test_historical_role_is_protected():
    with pytest.raises(ValueError, match='historical'):
        validate_placement(['Employer 2010–2013', 'Existing achievement'], 1)
    validate_placement(['Employer 2010–2013', 'Other employer 2014–Present', 'Current achievement'], 2)


def test_docx_addition_preserves_original_and_existing_content(tmp_path: Path):
    original = tmp_path / 'original.docx'
    output = tmp_path / 'updated.docx'
    doc = Document()
    for value in ['Past role 2010–2013', 'Historical achievement', 'Current role 2014–Present', 'Existing current achievement']:
        doc.add_paragraph(value)
    doc.save(original)
    before = original.read_bytes()
    append_bullets(original, output, 3, 'Existing current achievement', ['Reviewed security settings across 20 systems.'])
    assert original.read_bytes() == before
    updated = read_document(output.read_bytes(), '.docx')
    assert updated[:-1] == read_document(before, '.docx')
    assert updated[-1] == 'Reviewed security settings across 20 systems.'


def test_changed_anchor_refuses_output(tmp_path: Path):
    original = tmp_path / 'original.docx'
    doc = Document()
    doc.add_paragraph('Current content')
    doc.save(original)
    output = tmp_path / 'updated.docx'
    with pytest.raises(ValueError, match='placement changed'):
        append_bullets(original, output, 0, 'Stale content', ['New bullet'])
    assert not output.exists()


def test_complex_docx_layout_is_not_silently_rebuilt(tmp_path: Path):
    source = tmp_path / 'table.docx'
    doc = Document()
    doc.add_table(rows=1, cols=2)
    doc.save(source)
    with pytest.raises(ValueError, match='tables/text boxes'):
        read_document(source.read_bytes(), '.docx')


def test_current_role_choices_use_resume_text():
    from app.services.resumes import role_choices
    choices = role_choices(['Professional Experience', 'Acme Corporation', 'Systems Administrator', 'January 2014 – Present', 'Maintained infrastructure.', 'Old employer 2010–2013'])
    assert len(choices) == 1
    assert choices[0]['label'] == 'Acme Corporation — Systems Administrator — January 2014 – Present'
    assert choices[0]['anchor'] == 3
    assert choices[0]['current'] is True


def test_multiple_current_roles_require_a_choice():
    from app.services.resumes import role_choices
    choices = role_choices(['Acme Administrator 2014–Present', 'Beta Consultant 2023–Current'])
    assert len(choices) == 2
    assert all(choice['current'] for choice in choices)


def test_ambiguous_resume_offers_existing_text_without_inventing_role():
    from app.services.resumes import role_choices
    choices = role_choices(['Professional Experience', 'Acme Corporation', 'Systems Administrator'])
    assert [c['label'] for c in choices] == ['Acme Corporation', 'Systems Administrator']
    assert not any(c['current'] for c in choices)


def test_resume_changes_are_atomic_and_protect_history():
    from app.services.resume_changes import preview, validate_changes
    original = ['Current role 2014–Present', 'Keep this responsibility', 'Old achievement', 'Earlier role 2010–2013']
    change = {'kind': 'replace', 'targets': [2], 'text': 'Confirmed stronger achievement', 'source_ids': ['source']}
    validate_changes(original, [change], 0, 3, [1])
    assert preview(original, [change], 0) == [original[0], original[1], change['text'], original[3]]
    with pytest.raises(ValueError):
        validate_changes(original, [dict(change, targets=[1])], 0, 3, [1])
    with pytest.raises(ValueError):
        validate_changes(original, [dict(change, targets=[3])], 0, 3, [])
    with pytest.raises(ValueError):
        validate_changes(original, [change, change], 0, 3, [])


def test_saved_replacement_matches_preview(tmp_path):
    from app.services.resume_changes import preview, write_changes
    original = ['Current role 2014–Present', 'First contribution', 'Second contribution', 'Historical role 2010–2013']
    source, destination = tmp_path / 'source.docx', tmp_path / 'result.docx'
    doc = Document()
    for value in original:
        doc.add_paragraph(value)
    doc.save(source)
    changes = [{'kind': 'combine', 'targets': [1, 2], 'text': 'Combined contributions without invented totals'}]
    write_changes(source, destination, original, changes, 0)
    assert read_document(destination.read_bytes(), '.docx') == preview(original, changes, 0)
    assert read_document(source.read_bytes(), '.docx') == original
