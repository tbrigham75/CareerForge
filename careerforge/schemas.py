from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AccomplishmentStatus, Sensitivity


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(SetupRequest):
    pass


class AccomplishmentCreate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    raw_note: str | None = Field(default=None, max_length=20_000)
    action: str | None = Field(default=None, max_length=20_000)
    metric: str | None = Field(default=None, max_length=20_000)
    impact: str | None = Field(default=None, max_length=20_000)
    narrative: str | None = Field(default=None, max_length=50_000)
    date_started: date | None = None
    date_completed: date | None = None
    status: AccomplishmentStatus = AccomplishmentStatus.RAW_NOTE
    sensitivity: Sensitivity = Sensitivity.PRIVATE_PERSONAL
    github_export_eligible: bool = False

    @model_validator(mode="after")
    def has_content(self):
        if not any([self.raw_note, self.action, self.title]):
            raise ValueError("Provide a raw note, action, or title.")
        return self


class AccomplishmentUpdate(AccomplishmentCreate):
    pass


class AccomplishmentResponse(AccomplishmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_origin: str
    revision: int
    created_at: datetime
    updated_at: datetime


class AIProviderCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=10, max_length=500)
    provider_class: str = Field(pattern="^(local|remote)$")
    default_model: str = Field(min_length=1, max_length=160)
    api_token: str | None = Field(default=None, max_length=2048)
    is_default: bool = False


class AIProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    base_url: str
    provider_class: str
    default_model: str
    enabled: bool
    is_default: bool
    has_api_token: bool


class DraftRequest(BaseModel):
    raw_note: str = Field(min_length=1, max_length=20_000)
    provider_id: UUID | None = None


class DraftResponse(BaseModel):
    title: str
    action: str
    metric: str
    impact: str
    supporting_narrative: str
    placeholders_requiring_confirmation: list[str]
    follow_up_questions: list[str]
    confidence_notes: str
