"""Labels are registered in the same transaction as an accomplishment."""

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models import Category, Competency, Skill, SystemService, Tag, Technology

GROUPS = {
    "system/service": SystemService,
    "technology": Technology,
    "tag": Tag,
    "category": Category,
    "skill": Skill,
    "competency": Competency,
}
FIELDS = {"systems": SystemService, "technologies": Technology, "tags": Tag, "categories": Category}


def register(session: Session, model, names: list[str]) -> list[str]:
    result = []
    seen = set()
    for entry in names:
        for part in entry.split(","):
            name = part.strip()
            key = name.casefold()
            if not key or key in seen:
                continue
            if len(name) > 150:
                raise ValueError("Each reusable label must be 150 characters or fewer.")
            seen.add(key)
            existing = session.scalar(select(model.name).where(model.name_key == key))
            if existing is not None:
                result.append(existing)
                continue
            session.execute(
                insert(model)
                .values(name=name, name_key=key)
                .on_conflict_do_nothing(index_elements=["name_key"])
            )
            result.append(session.scalars(select(model.name).where(model.name_key == key)).one())
    return result


def register_record(session: Session, record) -> None:
    for field, model in FIELDS.items():
        setattr(record, field, register(session, model, getattr(record, field)))


def suggestions(session: Session) -> dict[str, list[str]]:
    return {
        field: list(
            {
                name.strip().casefold(): name
                for name in session.scalars(select(model.name).order_by(model.name.desc()))
            }.values()
        )[::-1]
        for field, model in FIELDS.items()
    }
