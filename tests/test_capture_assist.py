from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Accomplishment, AIProvider
from app.schemas import AIDraftResponse
from test_auth_and_capture import token


def test_assist_setup_and_csrf(logged_in):
    page = logged_in.get("/capture")
    assert "set up an AI provider first" in page.text
    assert 'href="/providers"' in page.text
    assert logged_in.post("/capture/assist", data={"csrf": "wrong"}).status_code == 403
    response = logged_in.post(
        "/capture/assist", data={"csrf": token(logged_in), "raw_note": "Work"}
    )
    assert response.json()["setup_url"] == "/providers"


def test_assist_remote_confirmation_and_no_save(logged_in, monkeypatch):
    with SessionLocal() as session:
        provider = AIProvider(
            display_name="Test",
            base_url="https://example.com",
            default_model="test",
            classification="remote",
        )
        session.add(provider)
        session.commit()
        provider_id = provider.id
    generate = AsyncMock(
        return_value=AIDraftResponse(
            title="Patched servers",
            action="Patched four servers.",
            metric="",
            impact="",
            supporting_narrative="",
            suggested_systems=["Linux"],
        )
    )
    monkeypatch.setattr("app.main.generate_draft", generate)
    data = {
        "csrf": token(logged_in),
        "provider_id": provider_id,
        "raw_note": "Patched four Linux servers.",
        "follow_up_answers": "Question: What outcome?\nAnswer: Verified all services restarted.",
    }
    review = logged_in.post("/capture/assist", data=data).json()
    assert review["confirmation_required"]
    assert review["follow_up_answers"] == data["follow_up_answers"]
    generate.assert_not_awaited()
    data["remote_confirmation"] = "true"
    result = logged_in.post("/capture/assist", data=data).json()["draft"]
    assert generate.await_args.args[1] == data["raw_note"]
    assert generate.await_args.args[2]["follow_up_answers"] == data["follow_up_answers"]
    assert result["action"] == "Patched four servers."
    assert result["metric"] == "[More information needed]"
    assert result["impact"] == "[More information needed]"
    assert set(result["field_questions"]) == {"metric", "impact"}
    assert "four Linux servers" in result["field_questions"]["metric"]
    generate.return_value = AIDraftResponse(
        title="Patched",
        action="Patched servers",
        metric="[missing-information]",
        impact="Verified services restarted.",
        metric_question="How many servers were patched?",
        supporting_narrative="",
    )
    targeted = logged_in.post("/capture/assist", data=data).json()["draft"]
    assert targeted["field_questions"] == {"metric": "How many servers were patched?"}
    generate.return_value = AIDraftResponse(
        title="Tracked services",
        action="Built tracker",
        metric="12 services",
        impact="Team can see changes between runs",
        metric_question="How many services?",
        impact_question="What changed?",
        questions=["What are your future plans?"],
        supporting_narrative="",
    )
    complete = logged_in.post("/capture/assist", data=data).json()["draft"]
    assert complete["field_questions"] == {}
    assert complete["questions"] == []
    generate.return_value = AIDraftResponse(
        title="",
        action="",
        metric="Reviewed 24 CIS settings.",
        impact="Provided the basis for compatibility decisions.",
        supporting_narrative="This must not be applied",
    )
    for field, answer, expected in [
        ("metric", "24 settings", "Reviewed 24 CIS settings."),
        (
            "impact",
            "helped compatibility decisions",
            "Provided the basis for compatibility decisions.",
        ),
    ]:
        targeted_data = {
            **data,
            "target_field": field,
            "target_answer": answer,
            "target_question": "What did you confirm?",
        }
        rewritten = logged_in.post("/capture/assist", data=targeted_data)
        assert rewritten.json() == {"field": field, "suggestion": expected}
        assert generate.await_args.args[2]["target_field"] == field
        review = logged_in.post(
            "/capture/assist", data={**targeted_data, "remote_confirmation": "false"}
        ).json()
        assert answer in review["follow_up_answers"]
    assert (
        logged_in.post(
            "/capture/assist", data={**data, "target_field": "title", "target_answer": "x"}
        ).status_code
        == 400
    )
    generate.return_value = AIDraftResponse(
        title="", action="", metric="", impact="", supporting_narrative="Reviewed 24 settings."
    )
    assert (
        logged_in.post(
            "/capture/assist",
            data={**data, "target_field": "metric", "target_answer": "24 settings"},
        ).status_code
        == 502
    )
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Accomplishment)) == 0
    generate.side_effect = RuntimeError("private failure")
    response = logged_in.post("/capture/assist", data=data)
    assert response.status_code == 502
    assert "private failure" not in response.text
    data["follow_up_answers"] = "x" * 20_001
    assert logged_in.post("/capture/assist", data=data).status_code == 400


def test_targeted_rewrite_accepts_only_requested_field(monkeypatch):
    import asyncio
    import json

    from app.models import AIProvider
    from app.services import ai

    class Response:
        content = json.dumps({"response": json.dumps({"metric": "Reviewed 24 settings."})}).encode()

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(ai.httpx, "AsyncClient", Client)
    provider = AIProvider(
        base_url="http://localhost:11434",
        default_model="test",
        timeout_seconds=30,
        retry_attempts=0,
    )
    draft = asyncio.run(
        ai.generate_draft(
            provider, "Reviewed settings", {"target_field": "metric", "follow_up_answers": "24"}
        )
    )
    assert draft.metric == "Reviewed 24 settings."
    assert draft.impact == draft.supporting_narrative == draft.action == draft.title == ""
