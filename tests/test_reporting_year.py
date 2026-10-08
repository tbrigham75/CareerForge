from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment, ReportingSettings
from app.services import reporting_year as years
from test_auth_and_capture import token


def preference(month=1, mode="calendar", naming="ending", timezone="UTC"):
    return ReportingSettings(
        id=1, mode=mode, start_month=month, year_naming=naming, timezone=timezone
    )


@pytest.mark.parametrize("month", range(1, 13))
def test_all_fiscal_months_and_both_naming_conventions(month):
    settings = preference(month, "fiscal")
    period = years.period_for(date(2026, month, 1), settings)
    assert period.start == date(2026, month, 1)
    assert period.label == f"FY {period.end.year}"
    assert years.period_for(period.end, settings) == period
    settings.year_naming = "starting"
    assert years.period_for(period.start, settings).label == "FY 2026"


def test_leap_year_midnight_timezone_and_rollover():
    settings = preference(10, "fiscal", timezone="America/Denver")
    before = years.current_period(settings, datetime(2026, 10, 1, 5, 59, tzinfo=UTC))
    after = years.current_period(settings, datetime(2026, 10, 1, 6, 0, tzinfo=UTC))
    assert before.label == "FY 2026" and before.end == date(2026, 9, 30)
    assert after.label == "FY 2027" and after.start == date(2026, 10, 1)
    assert years.period_for(date(2024, 2, 29), preference(3, "fiscal")).end == date(2024, 2, 29)
    calendar = preference(10, "calendar", timezone="Pacific/Auckland")
    assert years.current_period(calendar, datetime(2025, 12, 31, 11, 0, tzinfo=UTC)).label == "2026"


def test_views_keep_unfinished_notes_and_reports_accessible(logged_in, monkeypatch):
    monkeypatch.setattr(
        years, "current_period", lambda settings: years.period_for(date(2026, 10, 8), settings)
    )
    with SessionLocal() as session:
        session.add_all(
            [
                Accomplishment(
                    title="PastCompleted", status="completed", date_completed=date(2025, 6, 1)
                ),
                Accomplishment(
                    title="CurrentCompleted", status="completed", date_completed=date(2026, 3, 1)
                ),
                Accomplishment(
                    title="FutureCompleted", status="completed", date_completed=date(2027, 3, 1)
                ),
                Accomplishment(
                    title="OldUnfinished", status="in_progress", date_completed=date(2024, 6, 1)
                ),
                Accomplishment(title="UndatedCompleted", status="completed"),
                Accomplishment(
                    title="PastArchived",
                    status="completed",
                    is_archived=True,
                    date_completed=date(2025, 6, 1),
                ),
                Accomplishment(
                    title="PastDeleted",
                    status="completed",
                    deleted_at=datetime.now(UTC),
                    date_completed=date(2025, 6, 1),
                ),
            ]
        )
        session.commit()
    current = logged_in.get("/accomplishments").text
    assert all(
        title in current for title in ["CurrentCompleted", "OldUnfinished", "UndatedCompleted"]
    )
    assert all(
        title not in current
        for title in ["PastCompleted", "PastArchived", "FutureCompleted", "PastDeleted"]
    )
    history = logged_in.get("/history?year=2025-01-01&q=Past").text
    assert "PastCompleted" in history and "PastArchived" not in history
    assert "OldUnfinished" not in history and "PastDeleted" not in history
    assert "PastArchived" in logged_in.get("/history?archived=true").text
    assert "FutureCompleted" in logged_in.get("/accomplishments?scope=all").text
    assert "PastCompleted" in logged_in.get("/reports").text
    assert logged_in.get("/history?year=garbage").status_code == 400
    assert logged_in.get("/accomplishments?scope=invalid").status_code == 400
    assert "PastCompleted" not in logged_in.get("/history?date_from=2025-07-01").text
    with SessionLocal() as session:
        assert len(list(session.scalars(select(Accomplishment)))) == 7


def test_settings_preview_save_validation_and_regrouping(logged_in, monkeypatch):
    monkeypatch.setattr(
        years, "current_period", lambda settings: years.period_for(date(2026, 10, 8), settings)
    )
    with SessionLocal() as session:
        record = Accomplishment(
            title="SeptemberWork", status="completed", date_completed=date(2026, 9, 30)
        )
        session.add(record)
        session.commit()
        record_id = record.id
    data = {
        "csrf": token(logged_in),
        "mode": "fiscal",
        "start_month": "10",
        "year_naming": "ending",
        "timezone": "America/Denver",
    }
    preview = logged_in.post("/reporting-year", data={**data, "action": "preview"})
    assert preview.status_code == 200 and "Preview: FY 2027" in preview.text
    with SessionLocal() as session:
        assert session.get(ReportingSettings, 1) is None
    assert "SeptemberWork" in logged_in.get("/accomplishments").text
    assert logged_in.post("/reporting-year", data={**data, "csrf": "bad"}).status_code == 403
    for invalid in [
        {"start_month": "13"},
        {"mode": "invalid"},
        {"timezone": "Not/A_Zone"},
        {"year_naming": "invalid"},
    ]:
        assert logged_in.post("/reporting-year", data={**data, **invalid}).status_code == 400
    assert logged_in.post("/reporting-year", data=data).status_code == 200
    assert "SeptemberWork" not in logged_in.get("/accomplishments").text
    assert "SeptemberWork" in logged_in.get("/history?year=2025-10-01").text
    with SessionLocal() as session:
        assert session.get(ReportingSettings, 1).timezone == "America/Denver"
        record = session.get(Accomplishment, record_id)
        assert (
            record.date_completed == date(2026, 9, 30)
            and not record.is_archived
            and record.deleted_at is None
        )
    # Reverting the calendar regroups records without a data migration.
    assert logged_in.post("/reporting-year", data={**data, "mode": "calendar"}).status_code == 200
    assert "SeptemberWork" in logged_in.get("/accomplishments").text
    logged_in.cookies.clear()
    assert logged_in.get("/history", follow_redirects=False).status_code == 303
    assert logged_in.get("/reporting-year", follow_redirects=False).status_code == 303
