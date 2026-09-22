from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class AccomplishmentInput(BaseModel):
    title: str = Field(default="", max_length=300)
    raw_note: str = Field(default="", max_length=20_000)
    action: str = Field(default="", max_length=20_000)
    metric: str = Field(default="", max_length=20_000)
    impact: str = Field(default="", max_length=20_000)
    supporting_narrative: str = Field(default="", max_length=20_000)
    date_started: date | None = None
    date_completed: date | None = None
    systems: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    sensitivity: str = "private_personal"
    github_export: bool = False
    status: str = "draft"
    approval_status: str = "draft"

    @field_validator("sensitivity")
    @classmethod
    def sensitivity_is_allowed(cls, value: str) -> str:
        allowed = {"public_safe", "private_personal", "internal", "confidential", "do_not_sync"}
        if value not in allowed:
            raise ValueError("Unsupported sensitivity level.")
        return value


class AIProviderInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=150)
    base_url: str = Field(min_length=8, max_length=500)
    default_model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=10000, exclude=True)
    bearer_token: str = Field(default="", max_length=10000, exclude=True)
    custom_headers: dict[str, str] = Field(default_factory=dict, exclude=True)
    timeout_seconds: int = Field(default=60, ge=1, le=300)


class AIDraftResponse(BaseModel):
    title: str
    action: str
    metric: str
    impact: str
    supporting_narrative: str
    suggested_categories: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    suggested_technologies: list[str] = Field(default_factory=list)
    identified_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    quality_checks: list[str] = Field(default_factory=list)
