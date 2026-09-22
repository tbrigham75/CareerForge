from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


project_accomplishments = Table(
    "project_accomplishments",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id"), primary_key=True),
    Column("accomplishment_id", ForeignKey("accomplishments.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Accomplishment(Base):
    __tablename__ = "accomplishments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300), default="Untitled accomplishment")
    date_started: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_completed: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="raw_note", index=True)
    action: Mapped[str] = mapped_column(Text, default="")
    metric: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    supporting_narrative: Mapped[str] = mapped_column(Text, default="")
    raw_note: Mapped[str] = mapped_column(Text, default="")
    organization: Mapped[str] = mapped_column(String(200), default="")
    systems: Mapped[list[str]] = mapped_column(JSON, default=list)
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    competencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    sensitivity: Mapped[str] = mapped_column(String(30), default="private_personal", index=True)
    github_export: Mapped[bool] = mapped_column(Boolean, default=False)
    report_inclusion: Mapped[bool] = mapped_column(Boolean, default=True)
    source_origin: Mapped[str] = mapped_column(String(30), default="manual")
    approval_status: Mapped[str] = mapped_column(String(30), default="draft")
    source_path: Mapped[str] = mapped_column(Text, default="")
    source_hash: Mapped[str] = mapped_column(String(128), default="")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    revisions: Mapped[list[AccomplishmentRevision]] = relationship(
        back_populates="accomplishment", cascade="all, delete-orphan"
    )
    evidence_references: Mapped[list[EvidenceReference]] = relationship(
        back_populates="accomplishment", cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(
        secondary=project_accomplishments, back_populates="accomplishments"
    )


class AccomplishmentRevision(Base):
    __tablename__ = "accomplishment_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    accomplishment_id: Mapped[str] = mapped_column(ForeignKey("accomplishments.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(100), default="saved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accomplishment: Mapped[Accomplishment] = relationship(back_populates="revisions")


class AIDraft(Base):
    __tablename__ = "ai_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    accomplishment_id: Mapped[str | None] = mapped_column(
        ForeignKey("accomplishments.id"), nullable=True
    )
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("ai_providers.id"), nullable=True)
    model_name: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="review_required")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accomplishments: Mapped[list[Accomplishment]] = relationship(
        secondary=project_accomplishments, back_populates="projects"
    )


class EvidenceReference(Base):
    __tablename__ = "evidence_references"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    accomplishment_id: Mapped[str] = mapped_column(ForeignKey("accomplishments.id"), index=True)
    reference_type: Mapped[str] = mapped_column(String(50), default="other")
    reference_value: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accomplishment: Mapped[Accomplishment] = relationship(back_populates="evidence_references")


class NamedTaxonomy(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True)


class Category(NamedTaxonomy):
    __tablename__ = "categories"


class Tag(NamedTaxonomy):
    __tablename__ = "tags"


class Technology(NamedTaxonomy):
    __tablename__ = "technologies"


class Skill(NamedTaxonomy):
    __tablename__ = "skills"


class Competency(NamedTaxonomy):
    __tablename__ = "competencies"


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300))
    report_type: Mapped[str] = mapped_column(String(50), default="custom")
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportItem(Base):
    __tablename__ = "report_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    accomplishment_id: Mapped[str] = mapped_column(ForeignKey("accomplishments.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReportTemplate(Base):
    __tablename__ = "report_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    content: Mapped[str] = mapped_column(Text, default="")


class AIProvider(Base):
    __tablename__ = "ai_providers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(String(150), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    provider_type: Mapped[str] = mapped_column(String(50), default="ollama")
    base_url: Mapped[str] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(20), default="local")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_bearer_token: Mapped[str] = mapped_column(Text, default="")
    encrypted_headers: Mapped[str] = mapped_column(Text, default="")
    default_model: Mapped[str] = mapped_column(String(200), default="")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_state: Mapped[str] = mapped_column(String(30), default="unknown")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class GitRepositoryProfile(Base):
    __tablename__ = "git_repository_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    repository_path: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(String(200), default="main")
    export_subdirectory: Mapped[str] = mapped_column(String(300), default="accomplishments")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ExportRun(Base):
    __tablename__ = "export_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("git_repository_profiles.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    outcome: Mapped[str] = mapped_column(String(30), default="success")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttachmentMetadata(Base):
    __tablename__ = "attachment_metadata"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    accomplishment_id: Mapped[str | None] = mapped_column(
        ForeignKey("accomplishments.id"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128))
    sensitivity: Mapped[str] = mapped_column(String(30), default="private_personal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(300))
    source_hash: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(30))
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
