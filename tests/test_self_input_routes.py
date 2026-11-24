"""Prepared authenticated workflow checks using isolated data and a stubbed AI."""
import re
from copy import deepcopy
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment, AIProvider, AuditEvent, SelfInput
from app.services import self_input


@pytest.fixture
def assessment(logged_in):
    with SessionLocal() as session:
        session.add(Accomplishment(id="source", title="CIS review", status="completed", approval_status="approved",
                                  date_completed=date(2026, 6, 1), created_at=datetime(2026, 6, 1),
                                  action="Reviewed CIS settings", impact="Documented compatibility concerns"))
        session.add(AIProvider(id="local", display_name="Local test", base_url="http://127.0.0.1:11434", default_model="test"))
        session.commit()
    page = logged_in.get("/self-input?start=2026-01-01&end=2026-12-31")
    assert page.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = logged_in.post("/self-input", data={"csrf": token, "start": "2026-01-01", "end": "2026-12-31",
                             "source_ids": ["source"], "title": "My self input", "style": "narrative", "length": "standard",
                             "employer_questions": "What did I accomplish?"}, follow_redirects=False)
    assert response.status_code == 303
    record_id = response.headers["location"].rsplit("/", 1)[-1]
    return logged_in, record_id, token


def state_of(record_id):
    with SessionLocal() as session:
        record = session.get(SelfInput, record_id)
        return record.revision, deepcopy(record.state)


def submit(assessment, **fields):
    client, record_id, token = assessment
    revision, _ = state_of(record_id)
    data = {"csrf": token, "revision": str(revision), "provider": "local", "style": "narrative", "length": "standard"}
    data.update(fields)
    return client.post(f"/self-input/{record_id}/review", data=data)


def stub_generation(monkeypatch):
    async def propose(provider, state, section_id="", instruction=""):
        return {"custom-0": {"blocks": [{"id": "paragraph", "text": "I reviewed CIS settings and documented compatibility concerns.",
                                        "source_ids": ["source"], "locked": False}],
                             "questions": ["Which services did you assess?"]}}, {"source": {"excerpts": ["Reviewed CIS settings"]}}, {}
    monkeypatch.setattr(self_input, "propose", propose)
    async def selection(provider, instruction, data):
        return {"sections": [{"id": section["id"], "include": bool(section["paragraphs"]),
                              "reason": "This section explains the contribution."}
                             for section in data["selection_sections"]]}
    monkeypatch.setattr(self_input, "ask", selection)
    async def questions(provider, state, section):
        return state.get("proposals", {}).get(section["id"], section).get("questions", [])
    monkeypatch.setattr(self_input, "suggest_questions", questions)


def test_source_review_and_get_never_call_ai(assessment, monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("GET must not call AI")
    monkeypatch.setattr(self_input, "propose", fail)
    monkeypatch.setattr(self_input, "recommend_selection", fail)
    client, record_id, _ = assessment
    page = client.get(f"/self-input/{record_id}")
    assert page.status_code == 200
    assert "CIS review" in page.text
    assert "Generate all sections" in page.text
    assert state_of(record_id)[1]["sections"][0]["blocks"] == []


def test_single_checkbox_includes_and_confirms_unfinished_work(assessment):
    client, record_id, token = assessment
    with SessionLocal() as session:
        source = session.get(Accomplishment, "source")
        source.status = "raw_note"
        source.approval_status = "draft"
        session.commit()
    page = client.get(f"/self-input/{record_id}/sources")
    assert 'name="confirmed_source_ids"' in page.text
    revision, _ = state_of(record_id)
    response = client.post(f"/self-input/{record_id}/sources", data={
        "csrf": token, "revision": revision, "start": "2026-01-01", "end": "2026-12-31",
        "source_selection": "yes", "confirmed_source_ids": ["source"],
    }, follow_redirects=False)
    assert response.status_code == 303
    state = state_of(record_id)[1]
    assert list(state["sources"]) == ["source"]
    assert state["confirmed_ids"] == ["source"]
    with SessionLocal() as session:
        assert session.get(Accomplishment, "source").status == "raw_note"


def test_review_goals_persist_and_reject_oversized_replacements(assessment):
    goals = "Improve service reliability.\nSupport the CIS assessment."
    response = submit(assessment, operation="save", review_goals=goals)
    assert response.status_code == 200
    assert state_of(assessment[1])[1]["preferences"]["review_goals"] == goals
    assert "Improve service reliability." in response.text
    response = submit(assessment, operation="save", review_goals="x" * 12001)
    assert "12,000 characters" in response.text
    assert state_of(assessment[1])[1]["preferences"]["review_goals"] == goals
    submit(assessment, operation="save", review_goals="")
    assert state_of(assessment[1])[1]["preferences"]["review_goals"] == ""


def test_initial_sections_are_editable_but_exports_require_approval(assessment, monkeypatch):
    stub_generation(monkeypatch)
    response = submit(assessment, operation="generate")
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["blocks"]
    assert state["sections"][0]["included"] is True
    assert state["proposals"] == {}
    response = submit(assessment, operation="approve")
    assert "confirm that you reviewed" in response.text
    assert state_of(assessment[1])[1]["versions"] == []
    submit(assessment, operation="save", text_paragraph="I reviewed settings and documented compatibility concerns.")
    response = submit(assessment, operation="approve", confirm_review="yes")
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    version = state["versions"][0]
    download = assessment[0].get(f"/self-input/{assessment[1]}/versions/{version['id']}/txt")
    assert download.status_code == 200
    assert "I reviewed settings" in download.text
    assert "Which services" not in download.text
    submit(assessment, operation="save", text_paragraph="A later draft edit")
    unchanged = assessment[0].get(f"/self-input/{assessment[1]}/versions/{version['id']}/txt")
    assert unchanged.text == download.text


def test_failure_preserves_user_answers_and_draft(assessment, monkeypatch):
    async def fail(*args, **kwargs):
        raise TimeoutError("Provider unavailable")
    monkeypatch.setattr(self_input, "propose", fail)
    response = submit(assessment, operation="generate", **{"answer_custom-0": "I reviewed operational dependencies."})
    assert response.status_code == 200
    assert "Your draft was preserved" in response.text
    assert state_of(assessment[1])[1]["sections"][0]["answer"] == "I reviewed operational dependencies."


def test_stale_tab_cannot_overwrite_newer_answers(assessment):
    client, record_id, token = assessment
    old_revision = state_of(record_id)[0]
    submit(assessment, operation="save", **{"answer_custom-0": "Newest answer"})
    response = client.post(f"/self-input/{record_id}/review", data={"csrf": token, "revision": old_revision,
                           "operation": "save", "answer_custom-0": "Old answer"})
    assert response.status_code == 409
    assert state_of(record_id)[1]["sections"][0]["answer"] == "Newest answer"


def test_approval_requires_length_exception_and_handles_changed_evidence(assessment, monkeypatch):
    stub_generation(monkeypatch)
    submit(assessment, operation="generate")
    response = submit(assessment, operation="approve", confirm_review="yes", character_limit="5")
    assert "exceeds your character limit" in response.text
    assert state_of(assessment[1])[1]["versions"] == []
    with SessionLocal() as session:
        record = session.get(Accomplishment, "source")
        record.impact = "Corrected impact"
        session.commit()
    response = submit(assessment, operation="approve", confirm_review="yes")
    assert "source evidence changed" in response.text
    assert state_of(assessment[1])[1]["versions"] == []
    submit(assessment, operation="approve", confirm_review="yes", ack_stale="yes")
    assert len(state_of(assessment[1])[1]["versions"]) == 1


def test_unchecking_preserves_text_and_rewrites_require_acceptance(assessment, monkeypatch):
    stub_generation(monkeypatch)
    submit(assessment, operation="generate")
    submit(assessment, operation="save", inclusion_present="yes", text_paragraph="My edited contribution")
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["included"] is False
    assert self_input.plain_text(state["sections"]) == ""
    assert state["sections"][0]["blocks"][0]["text"] == "My edited contribution"
    submit(assessment, operation="generate", inclusion_present="yes")
    state = state_of(assessment[1])[1]
    assert "custom-0" in state["proposals"]
    assert state["sections"][0]["blocks"][0]["text"] == "My edited contribution"
    submit(assessment, operation="dismiss", inclusion_present="yes", included_sections=["custom-0"])
    assert "My edited contribution" in self_input.plain_text(state_of(assessment[1])[1]["sections"])


def test_ai_selection_is_explicit_after_first_generation_and_does_not_accept_rewrites(assessment, monkeypatch):
    stub_generation(monkeypatch)
    submit(assessment, operation="generate")
    initial = state_of(assessment[1])[1]
    assert initial["selection_recommendation"]["decisions"]["custom-0"]["include"] is True
    submit(assessment, operation="generate", inclusion_present="yes")
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["included"] is False
    assert "custom-0" in state["proposals"]
    response = submit(assessment, operation="select_ai", inclusion_present="yes")
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["included"] is True
    assert "custom-0" in state["proposals"]
    assert not state["versions"]


def test_recommend_existing_text_keeps_user_choices_and_rejects_stale_selection(assessment, monkeypatch):
    stub_generation(monkeypatch)
    submit(assessment, operation="generate")
    response = submit(assessment, operation="recommend", inclusion_present="yes", text_paragraph="My clearer contribution.")
    assert "AI recommends including this section" in response.text
    state = state_of(assessment[1])[1]
    assert not state["sections"][0]["included"]
    assert state["sections"][0]["blocks"][0]["text"] == "My clearer contribution."
    response = submit(assessment, operation="select_ai", inclusion_present="yes", text_paragraph="My newest wording.")
    assert "Ask AI to suggest a fresh section selection first" in response.text
    state = state_of(assessment[1])[1]
    assert not state["sections"][0]["included"]
    assert state["sections"][0]["blocks"][0]["text"] == "My newest wording."


def test_selection_failure_does_not_discard_successful_writing(assessment, monkeypatch):
    stub_generation(monkeypatch)
    async def fail(*args):
        raise TimeoutError("Private provider detail must not be exposed")
    monkeypatch.setattr(self_input, "recommend_selection", fail)
    response = submit(assessment, operation="generate")
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["blocks"]
    assert state["sections"][0]["included"] is True
    assert "could not suggest a section selection" in response.text
    assert "Private provider detail" not in response.text
    assert not state["error"]


def test_initial_recommendation_unchecks_empty_section_without_losing_questions(assessment, monkeypatch):
    stub_generation(monkeypatch)
    with SessionLocal() as session:
        record = session.get(SelfInput, assessment[1])
        state = deepcopy(record.state)
        state["sections"].append({"id": "development", "title": "Development", "prompt": "Development",
                                  "blocks": [], "questions": ["What did you learn?"], "answer": ""})
        record.state = state
        session.commit()
    submit(assessment, operation="generate")
    state = state_of(assessment[1])[1]
    assert state["sections"][1]["included"] is False
    assert state["sections"][1]["questions"] == ["What did you learn?"]
    assert state["selection_recommendation"]["decisions"]["development"]["include"] is False


def test_attachment_acknowledgment_is_required_before_generation(assessment, monkeypatch):
    calls = []
    async def observe(*args, **kwargs):
        calls.append(True)
        return {}, {}, {}
    monkeypatch.setattr(self_input, "propose", observe)
    with SessionLocal() as session:
        record = session.get(SelfInput, assessment[1])
        state = deepcopy(record.state)
        state["sources"]["source"]["attachments"] = [{"name": "Scanned.pdf", "issue": "No text layer", "text": ""}]
        record.state = state
        session.commit()
    response = submit(assessment, operation="generate")
    assert "Review the unavailable attachment text" in response.text
    assert calls == []


def test_csrf_and_authentication_protect_new_routes(client, assessment):
    logged_in, record_id, _ = assessment
    response = logged_in.post(f"/self-input/{record_id}/review", data={"revision": 0, "operation": "save"})
    assert response.status_code == 403
    # The client fixture is also used by logged_in, so explicitly clear its cookies.
    client.cookies.clear()
    response = client.get("/self-input", follow_redirects=False)
    assert response.status_code in {303, 401}


def test_delete_confirmation_removes_only_the_selected_assessment(assessment):
    client, record_id, token = assessment
    with SessionLocal() as session:
        record = session.get(SelfInput, record_id)
        state = deepcopy(record.state)
        state["versions"] = [{"id": "approved-version"}]
        record.state = state
        session.add(SelfInput(id="other-assessment", title=record.title, state=deepcopy(state)))
        session.commit()
    page = client.get("/self-input")
    assert f'href="/self-input/{record_id}/delete"' in page.text
    confirmation = client.get(f"/self-input/{record_id}/delete")
    assert confirmation.status_code == 200
    assert "1 approved version(s)" in confirmation.text
    assert "cannot be recovered from Trash" in confirmation.text
    revision, _ = state_of(record_id)  # GET must not delete.
    response = client.post(f"/self-input/{record_id}/delete", data={
        "csrf": token, "revision": revision, "confirm_delete": "yes",
    })
    assert response.status_code == 200
    assert "Self input deleted" in response.text
    with SessionLocal() as session:
        assert session.get(SelfInput, record_id) is None
        assert session.get(SelfInput, "other-assessment") is not None
        assert session.get(Accomplishment, "source") is not None
        event = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "self_input.deleted"))
        assert event.metadata_json == {"self_input_id": record_id}
    assert client.get(f"/self-input/{record_id}").status_code == 404
    assert client.get(f"/self-input/{record_id}/versions/approved-version/txt").status_code == 404


def test_delete_requires_csrf_confirmation_and_current_revision(assessment):
    client, record_id, token = assessment
    revision, _ = state_of(record_id)
    path = f"/self-input/{record_id}/delete"
    assert client.post(path, data={"revision": revision, "confirm_delete": "yes"}).status_code == 403
    assert client.post(path, data={"csrf": token, "revision": revision}).status_code == 400
    submit(assessment, operation="save", **{"answer_custom-0": "My newly saved answer"})
    response = client.post(path, data={"csrf": token, "revision": revision, "confirm_delete": "yes"})
    assert response.status_code == 409
    assert state_of(record_id)[1]["sections"][0]["answer"] == "My newly saved answer"
    client.cookies.clear()
    assert client.get(path, follow_redirects=False).status_code in {303, 401}
    assert client.post(path, data={"csrf": token, "revision": revision + 1, "confirm_delete": "yes"},
                       follow_redirects=False).status_code in {303, 401}
    assert state_of(record_id)[1]["sections"][0]["answer"] == "My newly saved answer"


def add_assessment_copies(record_id):
    with SessionLocal() as session:
        state = deepcopy(session.get(SelfInput, record_id).state)
        state["versions"] = [{"id": "old-version"}]
        for key in ("second-assessment", "keep-assessment"):
            session.add(SelfInput(id=key, title=key, state=deepcopy(state)))
        session.commit()


def test_fill_empty_section_includes_grounded_text_and_keeps_other_writing(assessment, monkeypatch):
    stub_generation(monkeypatch)
    with SessionLocal() as session:
        record = session.get(SelfInput, assessment[1])
        state = deepcopy(record.state)
        state["sections"][0].update(draft_initialized=True, included=False)
        state["sections"].append({"id": "summary", "title": "Summary", "prompt": "Summary", "answer": "",
                                  "questions": [], "included": True,
                                  "blocks": [{"id": "my-paragraph", "text": "My existing words", "source_ids": [], "locked": True}]})
        record.state = state
        session.commit()
    response = submit(assessment, operation="fill:custom-0", inclusion_present="yes",
                      included_sections=["custom-0", "summary"], locked=["my-paragraph"],
                      **{"text_my-paragraph": "My edited words"})
    assert response.status_code == 200
    assert response.url.fragment == "self-combined-draft"
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["included"] is True
    assert "I reviewed CIS settings" in self_input.plain_text(state["sections"])
    assert state["sections"][0]["blocks"][0]["source_versions"]["source"] == state["sources"]["source"]["fingerprint"]
    assert state["sections"][1]["blocks"][0]["text"] == "My edited words"
    assert state["sections"][1]["blocks"][0]["locked"] is True
    assert state["proposals"] == {}
    assert state["versions"] == []


def test_fill_existing_section_just_includes_it_without_ai(assessment, monkeypatch):
    stub_generation(monkeypatch)
    submit(assessment, operation="generate")
    async def fail(*args):
        raise AssertionError("Including existing writing must not call AI")
    monkeypatch.setattr(self_input, "propose", fail)
    response = submit(assessment, operation="fill:custom-0", text_paragraph="My exact wording")
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    assert not state["error"]
    assert state["sections"][0]["included"] is True
    assert state["sections"][0]["blocks"][0]["text"] == "My exact wording"


def test_write_missing_sections_keeps_existing_text_and_selection(assessment, monkeypatch):
    stub_generation(monkeypatch)
    with SessionLocal() as session:
        record = session.get(SelfInput, assessment[1])
        state = deepcopy(record.state)
        state["sections"][0].update(included=False, draft_initialized=True)
        state["sections"].append({"id": "summary", "title": "Summary", "prompt": "Summary", "answer": "My answer",
                                  "questions": ["My existing question?"], "included": True,
                                  "blocks": [{"id": "mine", "text": "My original summary", "source_ids": [], "locked": True}]})
        record.state = state
        session.commit()
    original = self_input.propose
    async def missing(provider, state, **kwargs):
        assert provider.id == "local"
        assert kwargs["requested_ids"] == ["custom-0"]
        return await original(provider, state)
    monkeypatch.setattr(self_input, "propose", missing)
    response = submit(assessment, operation="generate_missing", locked=["mine"])
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["blocks"]
    assert state["sections"][0]["included"] is False
    assert state["sections"][1]["blocks"][0]["text"] == "My original summary"
    assert state["sections"][1]["blocks"][0]["locked"] is True
    assert state["sections"][1]["questions"] == ["My existing question?"]
    assert state["proposals"] == {}
    assert "2 of 2 sections have draft text" in response.text
    assert 'value="generate_missing"' not in response.text


@pytest.mark.parametrize("failure", [False, True])
def test_fill_without_supported_text_does_not_claim_to_include_empty_section(assessment, monkeypatch, failure):
    stub_generation(monkeypatch)
    async def propose(*args):
        if failure:
            raise TimeoutError("Private provider error")
        return {"custom-0": {"blocks": [], "questions": ["What results can you confirm?"]}}, {}, {}
    monkeypatch.setattr(self_input, "propose", propose)
    response = submit(assessment, operation="fill:custom-0", **{"answer_custom-0": "My saved answer"})
    assert response.status_code == 200
    state = state_of(assessment[1])[1]
    assert not state["sections"][0]["included"]
    assert state["sections"][0]["answer"] == "My saved answer"
    assert not self_input.plain_text(state["sections"])
    assert state["error"]
    assert "Private provider error" not in response.text
    if not failure:
        assert state["sections"][0]["questions"] == ["What results can you confirm?"]


def test_fill_does_not_silently_accept_pending_rewrite(assessment, monkeypatch):
    with SessionLocal() as session:
        record = session.get(SelfInput, assessment[1])
        state = deepcopy(record.state)
        state["sections"][0]["draft_initialized"] = True
        state["proposals"] = {"custom-0": {"blocks": [{"id": "proposal", "text": "Proposed words", "source_ids": []}], "questions": []}}
        record.state = state
        session.commit()
    response = submit(assessment, operation="fill:custom-0")
    assert "proposed wording waiting for review" in response.text
    state = state_of(assessment[1])[1]
    assert state["proposals"]["custom-0"]["blocks"][0]["text"] == "Proposed words"
    assert not state["sections"][0]["blocks"]


def test_every_writing_run_requests_fresh_questions_about_generated_content(assessment, monkeypatch):
    stub_generation(monkeypatch)
    calls = []
    async def questions(provider, state, section):
        candidate = state.get("proposals", {}).get(section["id"], section)
        calls.append([block["text"] for block in candidate["blocks"]])
        return [f"Which services were considered during review pass {len(calls)}?"]
    monkeypatch.setattr(self_input, "suggest_questions", questions)
    response = submit(assessment, operation="generate")
    assert "Which services were considered during review pass 1?" in response.text
    response = submit(assessment, operation="generate:custom-0")
    assert "Which services were considered during review pass 2?" in response.text
    assert len(calls) == 2
    assert all("I reviewed CIS settings" in paragraphs[0] for paragraphs in calls)
    state = state_of(assessment[1])[1]
    assert "pass 1" in state["sections"][0]["questions"][0]
    assert "pass 2" in state["proposals"]["custom-0"]["questions"][0]


def test_question_failure_keeps_generated_text_and_shows_retry(assessment, monkeypatch):
    stub_generation(monkeypatch)
    async def fail(*args):
        raise TimeoutError("Private provider details")
    monkeypatch.setattr(self_input, "suggest_questions", fail)
    response = submit(assessment, operation="generate")
    assert "AI could not suggest follow-up questions" in response.text
    state = state_of(assessment[1])[1]
    assert state["sections"][0]["blocks"]
    assert not state["error"]
    assert "Private provider details" not in response.text


def test_bulk_delete_preview_and_confirmation_preserve_unselected_work(assessment):
    client, record_id, token = assessment
    add_assessment_copies(record_id)
    ids = [record_id, "second-assessment"]
    response = client.post("/self-input/bulk-delete/preview", data={"csrf": token, "assessment_ids": ids})
    assert response.status_code == 200
    assert "Delete 2 selected self input(s)?" in response.text
    assert "1 approved version(s)" in response.text
    assert "keep-assessment" not in response.text
    assert state_of(record_id)[1]  # Preview does not delete.
    response = client.post("/self-input/bulk-delete/confirm", data={
        "csrf": token, "assessment_ids": ids + [record_id], "confirm_delete": "yes",
        "revision_" + record_id: state_of(record_id)[0], "revision_second-assessment": 0,
    })
    assert response.status_code == 200
    assert "Selected self inputs deleted" in response.text
    with SessionLocal() as session:
        assert session.get(SelfInput, record_id) is None
        assert session.get(SelfInput, "second-assessment") is None
        assert session.get(SelfInput, "keep-assessment") is not None
        assert session.get(Accomplishment, "source") is not None
        events = list(session.scalars(select(AuditEvent).where(AuditEvent.event_type == "self_input.deleted")))
        assert {event.metadata_json["self_input_id"] for event in events} == set(ids)


def test_bulk_delete_stale_or_missing_record_deletes_nothing(assessment):
    client, record_id, token = assessment
    add_assessment_copies(record_id)
    form = {"csrf": token, "assessment_ids": ["second-assessment", record_id], "confirm_delete": "yes",
            "revision_" + record_id: state_of(record_id)[0], "revision_second-assessment": 0}
    submit(assessment, operation="save", **{"answer_custom-0": "New answer"})
    assert client.post("/self-input/bulk-delete/confirm", data=form).status_code == 409
    with SessionLocal() as session:
        assert session.get(SelfInput, "second-assessment") is not None
        assert session.get(SelfInput, record_id) is not None
        assert not list(session.scalars(select(AuditEvent).where(AuditEvent.event_type == "self_input.deleted")))
    form["assessment_ids"] = ["second-assessment", "missing-assessment"]
    assert client.post("/self-input/bulk-delete/confirm", data=form).status_code == 409
    assert state_of("second-assessment")[1]


def test_bulk_delete_requires_selection_confirmation_csrf_and_authentication(assessment):
    client, record_id, token = assessment
    for path in ("/self-input/bulk-delete/preview", "/self-input/bulk-delete/confirm"):
        assert client.post(path, data={"assessment_ids": [record_id]}).status_code == 403
        assert client.post(path, data={"csrf": token, "confirm_delete": "yes"}).status_code == 400
    assert client.post("/self-input/bulk-delete/confirm", data={"csrf": token, "assessment_ids": [record_id]}).status_code == 400
    assert client.post("/self-input/bulk-delete/confirm", data={
        "csrf": token, "assessment_ids": [record_id], "confirm_delete": "yes",
    }).status_code == 400
    client.cookies.clear()
    for path in ("/self-input/bulk-delete/preview", "/self-input/bulk-delete/confirm"):
        assert client.post(path, data={"csrf": token, "assessment_ids": [record_id]}, follow_redirects=False).status_code in {303, 401}
    assert state_of(record_id)[1]
