"""Prepared workflow regressions; AI is stubbed and all data uses test isolation."""
import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app import resume_routes
from app.db import SessionLocal
from app.models import AIProvider, Resume
from app.services import reporting_year


@pytest.fixture
def resume_workspace(logged_in, monkeypatch):
    with SessionLocal() as session:
        today = datetime.now(UTC).astimezone(ZoneInfo(reporting_year.preferences(session).timezone)).date()
        sources = {key: {'title': 'Accomplishment ' + key, 'action': 'Reviewed security settings.',
                         'metric': '', 'impact': 'Documented compatibility concerns.', 'organization': '',
                         'projects': [], 'completed': today.isoformat(), 'updated': 'v1'} for key in ('a', 'b', 'c')}
        paragraphs = ['Current role 2014–Present', 'Existing operational responsibility', 'Education']
        proposal = {'sources': {'a': sources['a']}, 'bullets': [
            {'kind': 'add', 'targets': [], 'text': 'Reviewed security settings.', 'source_ids': ['a'], 'reason': 'Relevant work'}],
            'year': today.year, 'role': paragraphs[0], 'anchor': 0, 'anchor_text': paragraphs[0],
            'start': 0, 'end': 2, 'protected': [0], 'budget': 100, 'baseline': paragraphs}
        session.add(Resume(id='resume-test', name='Example.docx', original_path='original.docx', original_hash='test',
                           state={'working': 'original.docx', 'paragraphs': paragraphs, 'proposal': proposal,
                                  'versions': [], 'used': [], 'rejected': [], 'preferences': {'goal': 'same', 'target': ''}}))
        session.add(AIProvider(id='local-test', display_name='Local test', base_url='http://127.0.0.1:11434', default_model='test'))
        session.commit()
    catalog = {'eligible': sources, 'excluded': [], 'counts': {}, 'year': today.year}
    monkeypatch.setattr(resume_routes.resume_sources, 'catalog', lambda *args: catalog)
    page = logged_in.get('/resumes/resume-test')
    assert page.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return logged_in, catalog, {'csrf': token, 'revision': '0', 'provider': 'local-test',
                               'bullet_0': 'My carefully edited wording.', 'selected': ['0']}


def provider_reply(monkeypatch, result=None, fail=False):
    requests = []

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            requests.append(kwargs['json'])
            if fail:
                raise TimeoutError('Simulated provider timeout')
            return self

        def raise_for_status(self):
            pass

        async def aiter_bytes(self):
            yield json.dumps({'response': json.dumps(result)}).encode()

    monkeypatch.setattr(resume_routes.httpx, 'AsyncClient', lambda **kwargs: Response())
    return requests


def saved_resume():
    with SessionLocal() as session:
        record = session.get(Resume, 'resume-test')
        return record.revision, record.state


def test_page_shows_all_three_sources_without_an_ai_call(resume_workspace, monkeypatch):
    client, _, _ = resume_workspace
    requests = provider_reply(monkeypatch, fail=True)
    page = client.get('/resumes/resume-test')
    assert page.status_code == 200
    assert all('Accomplishment ' + key in page.text for key in ('a', 'b', 'c'))
    assert '2 newly available' in page.text
    assert 'Suggest wording for this' in page.text
    assert requests == []


def test_refresh_keeps_existing_edits_and_appends_unselected_options(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    provider_reply(monkeypatch, {'bullets': [
        {'kind': 'add', 'targets': [], 'text': 'Documented compatibility concerns.', 'source_ids': ['b'], 'reason': 'Supported outcome'}]})
    response = client.post('/resumes/resume-test/update', data=data, follow_redirects=False)
    assert response.status_code == 303
    revision, state = saved_resume()
    assert revision == 2
    proposal = state['proposal']
    assert proposal['bullets'][0]['text'] == data['bullet_0']
    assert proposal['selected'] == ['0']
    assert len(proposal['bullets']) == 2
    assert proposal['bullets'][1]['new'] is True
    assert set(proposal['reviewed_sources']) == {'a', 'b', 'c'}
    assert state['working'] == 'original.docx'
    assert state['versions'] == []


def test_individual_request_only_sends_requested_source_and_does_not_select_it(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    requests = provider_reply(monkeypatch, {'bullets': [
        {'kind': 'add', 'targets': [], 'text': 'Documented compatibility concerns.', 'source_ids': ['b']}]})
    response = client.post('/resumes/resume-test/update', data=dict(data, source_id='b'), follow_redirects=False)
    assert response.status_code == 303
    proposal = saved_resume()[1]['proposal']
    assert proposal['bullets'][1]['alternative'] is True
    assert proposal['selected'] == ['0']
    assert set(proposal['reviewed_sources']) == {'a', 'b'}
    assert '"title": "Accomplishment b"' in requests[0]['prompt']
    assert '"title": "Accomplishment c"' not in requests[0]['prompt']


def test_failed_provider_keeps_submitted_draft_and_shows_retry_message(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    provider_reply(monkeypatch, fail=True)
    response = client.post('/resumes/resume-test/update', data=data)
    assert response.status_code == 200
    assert 'AI could not produce valid suggestions' in response.text
    state = saved_resume()[1]
    assert state['proposal']['bullets'][0]['text'] == data['bullet_0']
    assert state['proposal']['selected'] == ['0']
    assert state['versions'] == []


def test_changed_source_cannot_be_saved_by_reusing_old_wording(resume_workspace, monkeypatch):
    client, catalog, data = resume_workspace
    catalog['eligible']['a'] = dict(catalog['eligible']['a'], updated='v2')
    provider_reply(monkeypatch, {'bullets': []})
    response = client.post('/resumes/resume-test/update', data=data, follow_redirects=False)
    assert response.status_code == 303
    revision, state = saved_resume()
    assert state['proposal']['bullets'][0]['source_versions']['a'] == 'v1'
    response = client.post('/resumes/resume-test/review', data=dict(data, revision=str(revision), operation='save', allow_growth='yes'))
    assert response.status_code == 409
    assert saved_resume()[1]['versions'] == []


def test_overlapping_alternatives_can_be_generated_but_not_saved_together(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    provider_reply(monkeypatch, {'bullets': [
        {'kind': 'replace', 'targets': [1], 'text': 'Documented compatibility concerns.', 'source_ids': ['b']},
        {'kind': 'replace', 'targets': [1], 'text': 'Reviewed security settings.', 'source_ids': ['c']}]})
    response = client.post('/resumes/resume-test/update', data=data, follow_redirects=False)
    assert response.status_code == 303
    revision, state = saved_resume()
    assert len(state['proposal']['bullets']) == 3
    response = client.post('/resumes/resume-test/review', data=dict(data, revision=str(revision), operation='save',
                           selected=['1', '2'], bullet_1='Documented compatibility concerns.', bullet_2='Reviewed security settings.', allow_growth='yes'))
    assert response.status_code == 400
    assert saved_resume()[1]['versions'] == []


def test_stale_browser_revision_cannot_replace_draft(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    requests = provider_reply(monkeypatch, fail=True)
    response = client.post('/resumes/resume-test/review', data=dict(data, operation='draft'), follow_redirects=False)
    assert response.status_code == 303
    response = client.post('/resumes/resume-test/update', data=dict(data, bullet_0='Stale tab'), follow_redirects=False)
    assert response.status_code == 409
    assert saved_resume()[1]['proposal']['bullets'][0]['text'] == data['bullet_0']
    assert requests == []


def test_two_distinct_bullets_from_one_source_cannot_both_be_approved(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    provider_reply(monkeypatch, {'bullets': [
        {'kind': 'add', 'targets': [], 'text': 'Documented compatibility concerns.', 'source_ids': ['a']}]})
    client.post('/resumes/resume-test/update', data=dict(data, source_id='a'), follow_redirects=False)
    revision, state = saved_resume()
    assert len(state['proposal']['bullets']) == 2
    response = client.post('/resumes/resume-test/review', data=dict(data, revision=str(revision), operation='save',
                           selected=['0', '1'], bullet_1='Documented compatibility concerns.', allow_growth='yes'))
    assert response.status_code == 400
    assert 'same accomplishment' in response.text
    assert saved_resume()[1]['versions'] == []


def test_approved_option_creates_separate_document_and_preserves_original(resume_workspace):
    from docx import Document
    from app.config import get_settings
    from app.services.resumes import read_document

    client, _, data = resume_workspace
    state = saved_resume()[1]
    directory = get_settings().data_dir / 'resumes' / 'resume-test'
    directory.mkdir(parents=True, exist_ok=True)
    original = directory / 'original.docx'
    document = Document()
    for paragraph in state['paragraphs']:
        document.add_paragraph(paragraph)
    document.save(original)
    original_bytes = original.read_bytes()
    response = client.post('/resumes/resume-test/review', data=dict(data, operation='save', allow_growth='yes'), follow_redirects=False)
    assert response.status_code == 303
    state = saved_resume()[1]
    assert state['proposal'] is None
    assert len(state['versions']) == 1
    assert state['working'] != 'original.docx'
    assert original.read_bytes() == original_bytes
    assert read_document((directory / state['working']).read_bytes(), '.docx') == [
        'Current role 2014–Present', data['bullet_0'], 'Existing operational responsibility', 'Education']
    assert state['source_revisions']['a'] == 'v1'


def test_missing_provider_still_saves_user_edits_before_returning_configuration_error(resume_workspace):
    client, _, data = resume_workspace
    response = client.post('/resumes/resume-test/update', data=dict(data, provider='missing'), follow_redirects=False)
    assert response.status_code == 400
    assert saved_resume()[1]['proposal']['bullets'][0]['text'] == data['bullet_0']


def test_empty_ai_reply_explains_uncovered_source_in_inventory(resume_workspace, monkeypatch):
    client, _, data = resume_workspace
    provider_reply(monkeypatch, {'bullets': []})
    response = client.post('/resumes/resume-test/update', data=dict(data, source_id='b'))
    assert response.status_code == 200
    assert 'no usable wording or explanation' in response.text
    assert len(saved_resume()[1]['proposal']['bullets']) == 1


def test_generation_form_remains_available_without_a_draft(resume_workspace):
    client, _, _ = resume_workspace
    with SessionLocal() as session:
        record = session.get(Resume, 'resume-test')
        record.state = dict(record.state, proposal=None)
        session.commit()
    page = client.get('/resumes/resume-test')
    assert page.status_code == 200
    assert 'id="resume-generate"' in page.text
    assert 'Find resume suggestions' in page.text
    assert 'Give this accomplishment extra consideration' in page.text
    assert 'Tailor to a job — optional' in page.text
