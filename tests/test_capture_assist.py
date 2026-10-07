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
    assert len(result["questions"]) == 2
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Accomplishment)) == 0
    generate.side_effect = RuntimeError("private failure")
    response = logged_in.post("/capture/assist", data=data)
    assert response.status_code == 502
    assert "private failure" not in response.text
    data["follow_up_answers"] = "x" * 20_001
    assert logged_in.post("/capture/assist", data=data).status_code == 400
