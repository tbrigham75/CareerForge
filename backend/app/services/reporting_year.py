"""Date-based views: never move, archive, or delete accomplishments on rollover."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy.orm import Session

from app.models import Accomplishment, ReportingSettings


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str


def preferences(session: Session) -> ReportingSettings:
    return session.get(ReportingSettings, 1) or ReportingSettings(
        id=1, mode="calendar", start_month=1, year_naming="ending", timezone="UTC"
    )


def validate(mode: str, month: int, naming: str, timezone: str) -> None:
    if mode not in {"calendar", "fiscal"} or naming not in {"starting", "ending"}:
        raise ValueError("Choose a valid calendar and year naming convention.")
    if not 1 <= month <= 12:
        raise ValueError("Choose a starting month from January through December.")
    if timezone not in available_timezones():
        raise ValueError("Choose a valid organization timezone.")


def period_for(day: date, settings: ReportingSettings) -> Period:
    month = settings.start_month if settings.mode == "fiscal" else 1
    year = day.year - (day.month < month)
    start = date(year, month, 1)
    end = date(year + 1, month, 1) - timedelta(days=1)
    label_year = end.year if settings.year_naming == "ending" else start.year
    label = f"FY {label_year}" if settings.mode == "fiscal" else str(start.year)
    return Period(start, end, label)


def current_period(settings: ReportingSettings, now: datetime | None = None) -> Period:
    local_day = (now or datetime.now(UTC)).astimezone(ZoneInfo(settings.timezone)).date()
    return period_for(local_day, settings)


def is_finished(record: Accomplishment) -> bool:
    return record.status in {"completed", "archived"} and record.date_completed is not None


def current_records(records: list[Accomplishment], period: Period) -> list[Accomplishment]:
    return [
        record
        for record in records
        if not is_finished(record)
        or (
            record.date_completed is not None
            and period.start <= record.date_completed <= period.end
        )
    ]


def historical_records(records: list[Accomplishment], period: Period) -> list[Accomplishment]:
    return [
        record
        for record in records
        if is_finished(record)
        and record.date_completed is not None
        and record.date_completed < period.start
    ]
