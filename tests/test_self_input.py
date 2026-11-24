"""Prepared annual self-input regressions; no real provider is contacted."""
import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from docx import Document
from odf import teletype, text
from odf.opendocument import load
from starlette.datastructures import FormData

from app.db import SessionLocal
from app.models import Accomplishment, AttachmentMetadata, ReportingSettings
from app.services import reporting_year, self_input, self_input_exports, self_input_sources


def test_fiscal_and_custom_periods_include_previous_year_after_rollover():
    settings = ReportingSettings(mode="fiscal", start_month=10, year_naming="ending", timezone="America/Denver")
    result = self_input_sources.period(settings, "2026")
    assert (result.start, result.end, result.label) == (date(2025, 10, 1), date(2026, 9, 30), "FY 2026")
    settings.year_naming = "starting"
    result = self_input_sources.period(settings, "2026")
    assert (result.start, result.end) == (date(2026, 10, 1), date(2027, 9, 30))
    assert self_input_sources.period(settings, start="2024-02-01", end="2024-03-01").start == date(2024, 2, 1)
    with pytest.raises(ValueError):
        self_input_sources.period(settings, start="2026-12-01", end="2026-01-01")


def test_scope_includes_archived_work_and_requires_confirmation_for_notes():
    period = reporting_year.Period(date(2026, 1, 1), date(2026, 12, 31), "2026")
    with SessionLocal() as session:
        for key, fields in {
            "ready": {}, "archived": {"is_archived": True, "status": "archived"},
            "note": {"status": "raw_note", "approval_status": "draft"},
            "hidden": {"report_inclusion": False}, "trash": {"deleted_at": datetime(2026, 6, 1)},
            "old": {"date_completed": date(2025, 1, 1)},
        }.items():
            values = {"id": key, "title": key, "status": "completed", "approval_status": "approved",
                      "date_completed": date(2026, 6, 1), "created_at": datetime(2026, 6, 1)}
            session.add(Accomplishment(**dict(values, **fields)))
        session.commit()
        inventory = self_input_sources.catalog(session, period)
        assert {row["record"].id for row in inventory["ready"]} == {"ready", "archived"}
        assert {row["record"].id for row in inventory["review"]} == {"note"}
        assert {row["record"].id for row in inventory["excluded"]} == {"hidden"}
        with pytest.raises(ValueError, match="Confirm"):
            self_input_sources.collect(session, period, ["note"], set(), False)
        snapshot = self_input_sources.collect(session, period, ["note"], {"note"}, False)
        assert snapshot["note"]["status"] == "raw_note"
        assert session.get(Accomplishment, "note").approval_status == "draft"


def test_attachment_path_and_content_hash_are_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(self_input_sources, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    root = tmp_path / "attachments"
    root.mkdir()
    path = root / "facts.txt"
    path.write_text("Reviewed security settings.", encoding="utf-8")
    metadata = AttachmentMetadata(id="attachment", original_filename="facts.txt", stored_path=str(path),
                                  content_hash=hashlib.sha256(path.read_bytes()).hexdigest(), sensitivity="private_personal")
    assert self_input_sources.attachment_snapshot(metadata, True)["text"] == "Reviewed security settings."
    path.write_text("Changed facts.", encoding="utf-8")
    assert "content changed" in self_input_sources.attachment_snapshot(metadata, True)["issue"]
    metadata.stored_path = str(tmp_path / "outside.txt")
    assert "unavailable" in self_input_sources.attachment_snapshot(metadata, True)["issue"]
    assert "excluded by your choice" in self_input_sources.attachment_snapshot(metadata, False)["issue"]


def test_docx_evidence_extracts_table_text_and_keeps_original_bytes():
    doc = Document()
    doc.add_paragraph("Reviewed settings.")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Identified compatibility concerns."
    stream = BytesIO()
    doc.save(stream)
    original = stream.getvalue()
    result = self_input_sources.extract_document(original, ".docx")
    assert "Reviewed settings." in result
    assert "Identified compatibility concerns." in result
    assert stream.getvalue() == original


def test_locked_paragraphs_and_pending_proposal_edits_survive_draft_save():
    state = {"sections": [{"id": "results", "answer": "", "blocks": [
        {"id": "keep", "text": "My exact words", "locked": True, "source_ids": []},
        {"id": "replace", "text": "Old wording", "locked": False, "source_ids": []}]}],
        "proposals": {"results": {"blocks": [{"id": "new", "text": "AI wording", "source_ids": []}]}}}
    saved = self_input.capture(state, FormData([("locked", "keep"), ("proposal_new", "My proposal edit"), ("answer_results", "Confirmed detail")]))
    assert saved["proposals"]["results"]["blocks"][0]["text"] == "My proposal edit"
    merged = self_input.merge_locked(saved["sections"][0]["blocks"], saved["proposals"]["results"]["blocks"])
    assert [block["text"] for block in merged] == ["My exact words", "My proposal edit"]
    assert state["proposals"]["results"]["blocks"][0]["text"] == "AI wording"


def test_batches_include_all_text_without_silent_truncation():
    sources = {"a": {"notes": "x" * 50000}, "b": {"notes": "y" * 25000}}
    parts = [part for batch in self_input.evidence_batches(sources) for part in batch.values()]
    for source_id in sources:
        joined = "".join(part["text"] for part in parts if part["source_id"] == source_id)
        assert json.loads(joined) == sources[source_id]


def draft_state():
    return {"period": {"start": "2026-01-01", "end": "2026-12-31"},
            "preferences": {"style": "narrative", "length": "standard", "voice_sample": "I saved 900 hours in an earlier role."},
            "sources": {"a": {"title": "Security assessment", "status": "completed", "confirmation": "", "action": "Reviewed settings."}},
            "sections": [{"id": "results", "title": "Results", "prompt": "Results", "blocks": [], "answer": ""}],
            "digest": {"a": {"excerpts": ["Reviewed settings and documented compatibility concerns."]}}}


def test_ai_cannot_import_numbers_from_voice_sample(monkeypatch):
    async def fake_ask(*args):
        return {"sections": [{"id": "results", "blocks": [{"text": "I saved 900 hours.", "source_ids": ["a"]}], "questions": []}]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    with pytest.raises(ValueError, match="numeric"):
        asyncio.run(self_input.propose(None, draft_state()))


def test_review_goals_guide_ai_but_target_numbers_are_not_evidence(monkeypatch):
    state = draft_state()
    state["preferences"]["review_goals"] = "Reduce operational incidents by 37 percent."

    async def fake_ask(provider, instruction, data):
        assert data["preferences"]["review_goals"] in (state["preferences"]["review_goals"], "")
        assert "NEVER evidence" in instruction
        return {"sections": [{"id": "results", "blocks": [{"text": "I reduced incidents by 37 percent.", "source_ids": ["a"]}], "questions": []}]}

    monkeypatch.setattr(self_input, "ask", fake_ask)
    with pytest.raises(ValueError, match="numeric"):
        asyncio.run(self_input.propose(None, state))


def test_specific_questions_stay_outside_submission_text(monkeypatch):
    async def fake_ask(*args):
        return {"sections": [{"id": "results", "blocks": [{"text": "I reviewed settings and documented compatibility concerns.", "source_ids": ["a"]}],
                              "questions": ["Which services were affected?"]}]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    state = draft_state()
    proposals, _, _ = asyncio.run(self_input.propose(None, state))
    assert state["sections"][0]["blocks"] == []
    state["sections"][0].update(proposals["results"])
    assert "Which services" not in self_input.plain_text(state["sections"])
    assert self_input.coverage(state["sources"], state["sections"])[0]["sections"] == ["Results"]


def test_question_cleanup_removes_json_debris_and_preserves_real_questions():
    assert self_input.clean_questions([
        ']},{', "blocks':[{", 'source_ids', '"questions": []', '', None,
        'Which services?', 'How many systems did you review?', 'Which services?',
    ]) == ['Which services?', 'How many systems did you review?']


def test_numeric_repair_preserves_saved_goals_and_uses_evidence_only(monkeypatch):
    state = draft_state()
    state["preferences"]["review_goals"] = "Reduce incidents by 37 percent."
    before = deepcopy(state)
    calls = []

    async def fake_ask(provider, instruction, data):
        calls.append(data)
        wording = "I reduced incidents by 37 percent." if len(calls) == 1 else "I reviewed settings."
        return {"sections": [{"id": "results", "blocks": [{"text": wording, "source_ids": ["a"]}], "questions": []}]}

    monkeypatch.setattr(self_input, "ask", fake_ask)
    proposals, _, _ = asyncio.run(self_input.propose(None, state))
    assert proposals["results"]["blocks"][0]["text"] == "I reviewed settings."
    assert calls[1]["preferences"]["review_goals"] == ""
    assert state == before


def test_missing_section_numeric_repair_keeps_request_scope(monkeypatch):
    state = draft_state()
    state["sections"].append({"id": "summary", "title": "Summary", "prompt": "Summary", "answer": "",
                              "blocks": [{"text": "My existing summary.", "source_ids": []}]})
    calls = []
    async def fake_ask(provider, instruction, data):
        calls.append(data)
        assert [section["id"] for section in data["requested_sections"]] == ["results"]
        wording = "I saved 900 hours." if len(calls) == 1 else "I reviewed settings."
        return {"sections": [{"id": "results", "blocks": [{"text": wording, "source_ids": ["a"]}], "questions": []}]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    result, _, _ = asyncio.run(self_input.propose(None, state, requested_ids=["results"]))
    assert set(result) == {"results"}
    assert len(calls) == 2
    assert state["sections"][1]["blocks"][0]["text"] == "My existing summary."


def test_self_input_ai_rejects_cloud_provider_before_network_request(monkeypatch):
    provider = SimpleNamespace(enabled=True, default_model="model", base_url="https://example.com")
    def unexpected(**kwargs):
        raise AssertionError("A cloud provider must never be contacted")
    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    with pytest.raises(ValueError, match="local/private-network"):
        asyncio.run(self_input.ask(provider, "Write", {}))


def test_missing_section_is_requested_individually_without_replacing_returned_work(monkeypatch):
    state = draft_state()
    state["sections"].append({"id": "development", "title": "Development", "prompt": "Development", "blocks": [], "answer": ""})
    requests = []

    async def fake_ask(provider, instruction, data):
        requests.append(data)
        if len(requests) == 1:
            return {"sections": [{"id": "results", "blocks": [{"text": "I reviewed settings.", "source_ids": ["a"]}], "questions": []}]}
        assert [section["id"] for section in data["requested_sections"]] == ["development"]
        return {"sections": [{"id": "development", "blocks": [], "questions": ["What training did you complete?"]}]}

    monkeypatch.setattr(self_input, "ask", fake_ask)
    proposals, _, _ = asyncio.run(self_input.propose(None, state))
    assert proposals["results"]["blocks"][0]["text"] == "I reviewed settings."
    assert proposals["development"]["questions"] == ["What training did you complete?"]
    assert len(requests) == 2


def test_missing_section_recovery_has_a_finite_limit(monkeypatch):
    requests = []

    async def fake_ask(*args):
        requests.append(True)
        return {"sections": []}

    monkeypatch.setattr(self_input, "ask", fake_ask)
    with pytest.raises(ValueError, match="two focused attempts"):
        asyncio.run(self_input.propose(None, draft_state()))
    assert len(requests) == 3


def test_full_assessment_uses_focused_requests_with_all_evidence_and_prior_wording(monkeypatch):
    state = draft_state()
    state['preferences']['target_words'] = 700
    state['sections'].append({'id': 'collaboration', 'title': 'Collaboration', 'prompt': 'Teamwork', 'blocks': [], 'answer': ''})
    before = deepcopy(state)
    calls = []
    async def fake_ask(provider, instruction, data):
        calls.append(data)
        assert len(data['requested_sections']) == 1
        assert data['facts'] == state['digest']
        assert data['preferences']['section_word_target'] == 350
        key = data['requested_sections'][0]['id']
        return {'sections': [{'id': key, 'blocks': [{'text': 'I reviewed settings.', 'source_ids': ['a']}], 'questions': []}]}
    monkeypatch.setattr(self_input, 'ask', fake_ask)
    proposals, _, _ = asyncio.run(self_input.propose(None, state))
    assert set(proposals) == {'results', 'collaboration'}
    assert len(calls) == 2
    assert calls[0]['existing_proposals'] == []
    assert calls[1]['existing_proposals'][0]['id'] == 'results'
    assert state == before


def test_digest_preserves_original_evidence_without_model_quotation_copying(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("Ordinary selections need no evidence extraction AI call")
    monkeypatch.setattr(self_input, "ask", unexpected)
    sources = draft_state()["sources"]
    result = asyncio.run(self_input.digest(None, sources, {}))
    assert json.loads(result["a"]["excerpts"][0]) == sources["a"]


def test_digest_bad_passage_indexes_preserve_all_original_parts(monkeypatch):
    async def fake_ask(*args):
        return {"selected": ["altered quotation", -1, 999999]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    sources = draft_state()["sources"]
    sources["a"]["notes"] = "source facts " * 6000
    result = asyncio.run(self_input.digest(None, sources, {}))
    assert json.loads("".join(result["a"]["excerpts"])) == sources["a"]


def test_digest_passage_selection_uses_original_text(monkeypatch):
    expected = []
    async def fake_ask(provider, instruction, data):
        expected.append(data["passages"][0])
        return {"selected": [0]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    sources = draft_state()["sources"]
    sources["a"]["notes"] = "source facts " * 6000
    result = asyncio.run(self_input.digest(None, sources, {}))
    assert result["a"]["excerpts"] == expected

def test_word_and_odt_export_only_approved_text():
    sections = [{"id": "results", "title": "Results", "blocks": [{"text": "I reviewed settings.", "source_ids": ["private-id"]}],
                 "answer": "Internal detail", "questions": ["Internal question?"]}]
    sections.append({"id": "excluded", "title": "Excluded heading", "included": False,
                     "blocks": [{"text": "Excluded contribution", "source_ids": []}]})
    version = {"period": {"label": "2026"}, "sections": sections}
    before = deepcopy(version)
    word = Document(BytesIO(self_input_exports.export("My assessment", version, "docx")))
    word_text = "\n".join(p.text for p in word.paragraphs)
    odt = load(BytesIO(self_input_exports.export("My assessment", version, "odt")))
    odt_text = "\n".join(teletype.extractText(p) for p in odt.getElementsByType(text.P))
    for value in (word_text, odt_text, self_input_exports.export("My assessment", version, "txt").decode()):
        assert "I reviewed settings." in value
        assert "Internal" not in value
        assert "private-id" not in value
        assert "Excluded" not in value
    assert version == before


def test_section_selection_reviews_all_candidate_text_and_preserves_employer_questions(monkeypatch):
    state = draft_state()
    state["sections"][0]["blocks"] = [{"text": "My locked results.", "locked": True, "source_ids": ["a"]}]
    state["sections"].extend([
        {"id": "custom-0", "title": "Employer question", "blocks": [{"text": "My answer.", "source_ids": []}]},
        {"id": "development", "title": "Development", "blocks": []},
    ])
    state["proposals"] = {"results": {"blocks": [{"text": "My proposed wording.", "source_ids": ["a"]}]}}
    before = deepcopy(state)
    async def fake_ask(provider, instruction, data):
        assert data["selection_sections"][0]["paragraphs"] == ["My locked results.", "My proposed wording."]
        return {"sections": [
            {"id": "results", "include": True, "reason": "Distinct results."},
            {"id": "custom-0", "include": False, "reason": "Overlaps results."},
            {"id": "development", "include": True, "reason": "Learning adds context."},
        ]}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    recommendation = asyncio.run(self_input.recommend_selection(None, state))
    assert recommendation["decisions"]["custom-0"]["include"] is True
    assert recommendation["decisions"]["development"]["include"] is False
    assert state == before
    state["selection_recommendation"] = recommendation
    state["sections"][0]["included"] = False
    assert self_input.selection_is_current(state)
    state["sections"][0]["blocks"] = self_input.merge_locked(state["sections"][0]["blocks"], state["proposals"].pop("results")["blocks"])
    assert self_input.selection_is_current(state)
    state["sections"][0]["blocks"][0]["text"] = "Changed wording"
    assert not self_input.selection_is_current(state)


@pytest.mark.parametrize("values", [
    [], None,
    [{"id": "unknown", "include": True, "reason": "Include it."}],
    [{"id": "results", "include": "false", "reason": "Leave it out."}],
    [{"id": "results", "include": True, "reason": ""}],
    [{"id": "results", "include": False, "reason": "Skip everything."}],
    [{"id": "results", "include": True, "reason": "Include it."}] * 2,
])
def test_section_selection_rejects_incomplete_invalid_or_empty_recommendations(monkeypatch, values):
    state = draft_state()
    state["sections"][0]["blocks"] = [{"text": "My contribution.", "source_ids": ["a"]}]
    before = deepcopy(state)
    async def fake_ask(*args):
        return {"sections": values}
    monkeypatch.setattr(self_input, "ask", fake_ask)
    with pytest.raises(ValueError, match="choices are unchanged"):
        asyncio.run(self_input.recommend_selection(None, state))
    assert state == before


def test_streamed_generation_joins_split_unicode_events_and_requires_completion():
    payload = (json.dumps({"response": '{"questions":["Which café systems?"]}', "done": False}, ensure_ascii=False)
               + '\n' + json.dumps({"response": '', "done": True})).encode()
    class Stream:
        async def aiter_bytes(self):
            for byte in payload:
                yield bytes([byte])
    result = asyncio.run(self_input.read_generation(Stream(), len(payload)))
    assert result == {"questions": ["Which café systems?"]}


@pytest.mark.parametrize("payload,limit,message", [
    (b'{"response":"{}","done":false}\n', 1000, "before generation finished"),
    (b'{"response":"{","done":true}\n', 1000, "valid structured draft"),
    (b'{"error":"private provider detail"}\n', 1000, "could not finish"),
    (b'invalid\n', 1000, "malformed response"),
    (b'{"response":{},"done":true}\n', 1000, "could not finish"),
    (b'{"response":"{}","done":true}\n', 5, "configured limit"),
])
def test_streamed_generation_rejects_incomplete_malformed_and_oversized_output(payload, limit, message):
    class Stream:
        async def aiter_bytes(self):
            yield payload
    with pytest.raises(ValueError, match=message) as error:
        asyncio.run(self_input.read_generation(Stream(), limit))
    assert 'private provider detail' not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_ask_streams_output_and_explains_inactivity_timeout(monkeypatch, failure):
    provider = SimpleNamespace(enabled=True, default_model='local', base_url='http://127.0.0.1:11434', timeout_seconds=60)
    original_client = httpx.AsyncClient
    def respond(request):
        assert json.loads(request.content)['stream'] is True
        if failure:
            raise httpx.ReadTimeout('private endpoint details', request=request)
        return httpx.Response(200, content=b'{"response":"{\\"questions\\":[]}","done":true}\n')
    monkeypatch.setattr(self_input, '_headers', lambda provider: {})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    if failure:
        with pytest.raises(ValueError, match='no response data for 60 seconds') as error:
            asyncio.run(self_input.ask(provider, 'Ask a question', {'question_section': 'Results'}))
        assert 'private endpoint' not in str(error.value)
    else:
        assert asyncio.run(self_input.ask(provider, 'Ask a question', {'question_section': 'Results'})) == {'questions': []}


def test_ask_has_a_total_generation_deadline_as_well_as_inactivity_timeout(monkeypatch):
    provider = SimpleNamespace(enabled=True, default_model='local', base_url='http://127.0.0.1:11434', timeout_seconds=60)
    class ExpiredDeadline:
        async def __aenter__(self):
            raise TimeoutError()
        async def __aexit__(self, *args):
            return False
    def timeout(seconds):
        assert seconds == 300
        return ExpiredDeadline()
    monkeypatch.setattr(asyncio, 'timeout', timeout)
    with pytest.raises(ValueError, match='generation exceeded 300 seconds'):
        asyncio.run(self_input.ask(provider, 'Write', {}))


@pytest.mark.parametrize('style,target,limit', [('narrative', 140, 1), ('narrative', 240, 2), ('bullets', 140, 4)])
def test_section_response_size_tracks_requested_format_and_length(monkeypatch, style, target, limit):
    provider = SimpleNamespace(enabled=True, default_model='local', base_url='http://127.0.0.1:11434', timeout_seconds=60)
    original_client = httpx.AsyncClient
    def respond(request):
        schema = json.loads(request.content)['format']
        blocks = schema['properties']['sections']['items']['properties']['blocks']
        assert blocks['maxItems'] == limit
        assert blocks['items']['properties']['source_ids']['maxItems'] == 1
        assert schema['properties']['omissions']['additionalProperties'] is False
        return httpx.Response(200, content=b'{"response":"{\\"sections\\":[]}","done":true}\n')
    monkeypatch.setattr(self_input, '_headers', lambda provider: {})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(self_input.ask(provider, 'Write a concise section', {
        'requested_sections': [{'id': 'results'}], 'facts': {'source': {}},
        'preferences': {'style': style, 'section_word_target': target},
    }))
    assert result == {'sections': []}

