from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import get_session
from app.models import (
    Accomplishment,
    AIDraft,
    AIProvider,
    AttachmentMetadata,
    AuditEvent,
    Category,
    Competency,
    EvidenceReference,
    GitRepositoryProfile,
    ImportRun,
    Project,
    Report,
    ReportItem,
    ReportTemplate,
    Skill,
    Tag,
    Technology,
    User,
)
from app.schemas import AccomplishmentInput, AIProviderInput
from app.security import (
    csrf_token,
    encrypt_secret,
    hash_password,
    require_authenticated,
    require_csrf,
    verify_password,
)
from app.services import accomplishments, git_ops
from app.services.ai import (
    ProviderSafetyError,
    classify_and_validate_url,
    generate_draft,
    list_models,
)
from app.services.backup import BackupError, create_backup, validate_backup_archive
from app.services.exporter import export_markdown
from app.services.importer import import_odt
from app.services.reports import generate_docx

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app = FastAPI(title="CareerForge", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.encryption_key or secrets.token_urlsafe(32),
    https_only=settings.cookie_secure,
    same_site="lax",
    max_age=settings.session_timeout_minutes * 60,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
SessionDependency = Annotated[Session, Depends(get_session)]
_login_attempts: dict[str, list[datetime]] = defaultdict(list)


def context(request: Request, **values: object) -> dict[str, object]:
    return {
        "request": request,
        "csrf_token": csrf_token(request),
        "user_id": request.session.get("user_id"),
        **values,
    }


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def current_user(request: Request, session: SessionDependency) -> User:
    user_id = require_authenticated(request)
    user = session.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_date(value: str) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def form_to_accomplishment(
    title: str,
    raw_note: str,
    action: str,
    metric: str,
    impact: str,
    supporting_narrative: str,
    date_started: str,
    date_completed: str,
    systems: str,
    technologies: str,
    tags: str,
    categories: str,
    sensitivity: str,
    github_export: bool,
    status: str,
    approval_status: str,
) -> AccomplishmentInput:
    return AccomplishmentInput(
        title=title,
        raw_note=raw_note,
        action=action,
        metric=metric,
        impact=impact,
        supporting_narrative=supporting_narrative,
        date_started=parse_date(date_started),
        date_completed=parse_date(date_completed),
        systems=parse_list(systems),
        technologies=parse_list(technologies),
        tags=parse_list(tags),
        categories=parse_list(categories),
        sensitivity=sensitivity,
        github_export=github_export,
        status=status,
        approval_status=approval_status,
    )


@app.get("/")
def home(request: Request, session: SessionDependency):
    if not session.scalar(select(func.count()).select_from(User)):
        return redirect("/setup")
    return redirect("/dashboard" if request.session.get("user_id") else "/login")


@app.get("/setup")
def setup_page(request: Request, session: SessionDependency):
    if session.scalar(select(func.count()).select_from(User)):
        return redirect("/login")
    return templates.TemplateResponse("setup.html", context(request))


@app.post("/setup")
def setup(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
):
    require_csrf(request, csrf)
    if session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status_code=409, detail="Administrator account already exists.")
    if password != password_confirm:
        return templates.TemplateResponse(
            "setup.html", context(request, error="Passwords do not match."), status_code=400
        )
    try:
        user = User(username=username.strip(), password_hash=hash_password(password))
    except ValueError as exc:
        return templates.TemplateResponse(
            "setup.html", context(request, error=str(exc)), status_code=400
        )
    session.add(user)
    session.add(AuditEvent(event_type="admin.setup", metadata_json={"username": user.username}))
    session.commit()
    return redirect("/login")


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", context(request))


@app.post("/login")
def login(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    require_csrf(request, csrf)
    client = request.client.host if request.client else "unknown"
    now = datetime.now(UTC)
    _login_attempts[client] = [
        attempt for attempt in _login_attempts[client] if now - attempt < timedelta(minutes=15)
    ]
    if len(_login_attempts[client]) >= 8:
        return templates.TemplateResponse(
            "login.html",
            context(request, error="Too many login attempts. Try again later."),
            status_code=429,
        )
    user = session.scalar(select(User).where(User.username == username.strip()))
    if not user or not verify_password(password, user.password_hash):
        _login_attempts[client].append(now)
        session.add(
            AuditEvent(
                event_type="login", outcome="failed", metadata_json={"username": username.strip()}
            )
        )
        session.commit()
        return templates.TemplateResponse(
            "login.html", context(request, error="Invalid username or password."), status_code=401
        )
    request.session.clear()
    request.session.update(
        {
            "user_id": user.id,
            "expires_at": (now + timedelta(minutes=settings.session_timeout_minutes)).isoformat(),
            "csrf_token": secrets.token_urlsafe(32),
        }
    )
    session.add(AuditEvent(event_type="login", metadata_json={"user_id": user.id}))
    session.commit()
    return redirect("/dashboard")


@app.post("/logout")
def logout(request: Request, csrf: Annotated[str, Form()]):
    require_csrf(request, csrf)
    request.session.clear()
    return redirect("/login")


@app.get("/dashboard")
def dashboard(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    recent = accomplishments.search(session)[:8]
    count = (
        session.scalar(
            select(func.count())
            .select_from(Accomplishment)
            .where(Accomplishment.deleted_at.is_(None))
        )
        or 0
    )
    return templates.TemplateResponse(
        "dashboard.html", context(request, recent=recent, count=count)
    )


@app.get("/capture")
def capture_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    providers = list(session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True))))
    projects = list(session.scalars(select(Project).order_by(Project.name)))
    return templates.TemplateResponse(
        "capture.html", context(request, providers=providers, projects=projects, record=None)
    )


@app.post("/capture")
def capture(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    raw_note: Annotated[str, Form()] = "",
    action: Annotated[str, Form()] = "",
    metric: Annotated[str, Form()] = "",
    impact: Annotated[str, Form()] = "",
    supporting_narrative: Annotated[str, Form()] = "",
    date_started: Annotated[str, Form()] = "",
    date_completed: Annotated[str, Form()] = "",
    systems: Annotated[str, Form()] = "",
    technologies: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    categories: Annotated[str, Form()] = "",
    sensitivity: Annotated[str, Form()] = "private_personal",
    github_export: Annotated[bool, Form()] = False,
    action_choice: Annotated[str, Form()] = "raw",
    provider_id: Annotated[str, Form()] = "",
    project_id: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if not any((raw_note.strip(), action.strip(), metric.strip(), impact.strip())):
        providers = list(session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True))))
        projects = list(session.scalars(select(Project).order_by(Project.name)))
        return templates.TemplateResponse(
            "capture.html",
            context(
                request,
                providers=providers,
                projects=projects,
                record=None,
                error="Enter a raw note or accomplishment content.",
            ),
            status_code=400,
        )
    status = "raw_note" if action_choice == "raw" else "completed"
    approval = "draft" if action_choice == "raw" else "approved"
    data = form_to_accomplishment(
        title,
        raw_note,
        action,
        metric,
        impact,
        supporting_narrative,
        date_started,
        date_completed,
        systems,
        technologies,
        tags,
        categories,
        sensitivity,
        github_export,
        status,
        approval,
    )
    record = accomplishments.create(session, data)
    if project_id:
        project = session.get(Project, project_id)
        if project:
            record.projects.append(project)
            session.add(
                AuditEvent(
                    event_type="accomplishment.project_linked",
                    metadata_json={"record_id": record.id, "project_id": project.id},
                )
            )
            session.commit()
    if action_choice == "draft" and provider_id:
        return redirect(f"/ai/draft/{record.id}?provider_id={provider_id}")
    return redirect(f"/accomplishments/{record.id}")


@app.get("/accomplishments")
def archive(
    request: Request,
    session: SessionDependency,
    _: User = Depends(current_user),
    q: str = "",
    archived: bool = False,
    date_from: str = "",
    date_to: str = "",
    sensitivity: str = "",
    tag: str = "",
    technology: str = "",
    project_id: str = "",
):
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "sensitivity": sensitivity,
        "tag": tag,
        "technology": technology,
        "project_id": project_id,
    }
    return templates.TemplateResponse(
        "accomplishments.html",
        context(
            request,
            records=accomplishments.search(
                session,
                q,
                archived,
                parse_date(date_from),
                parse_date(date_to),
                sensitivity,
                tag,
                technology,
                project_id,
            ),
            query=q,
            archived=archived,
            projects=list(session.scalars(select(Project).order_by(Project.name))),
            filters=filters,
        ),
    )


def get_record(session: Session, record_id: str) -> Accomplishment:
    record = session.get(Accomplishment, record_id)
    if not record or record.deleted_at:
        raise HTTPException(status_code=404, detail="Accomplishment not found.")
    return record


@app.get("/accomplishments/{record_id}")
def detail(
    record_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    record = get_record(session, record_id)
    return templates.TemplateResponse(
        "detail.html",
        context(
            request,
            record=record,
            revisions=record.revisions,
            drafts=list(
                session.scalars(select(AIDraft).where(AIDraft.accomplishment_id == record.id))
            ),
            attachments=list(
                session.scalars(
                    select(AttachmentMetadata).where(
                        AttachmentMetadata.accomplishment_id == record.id
                    )
                )
            ),
        ),
    )


@app.get("/accomplishments/{record_id}/edit")
def edit_accomplishment_page(
    record_id: str,
    request: Request,
    session: SessionDependency,
    _: User = Depends(current_user),
):
    return templates.TemplateResponse(
        "edit_accomplishment.html", context(request, record=get_record(session, record_id))
    )


@app.post("/accomplishments/{record_id}/edit")
def edit_accomplishment(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    raw_note: Annotated[str, Form()] = "",
    action: Annotated[str, Form()] = "",
    metric: Annotated[str, Form()] = "",
    impact: Annotated[str, Form()] = "",
    supporting_narrative: Annotated[str, Form()] = "",
    date_started: Annotated[str, Form()] = "",
    date_completed: Annotated[str, Form()] = "",
    systems: Annotated[str, Form()] = "",
    technologies: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    categories: Annotated[str, Form()] = "",
    sensitivity: Annotated[str, Form()] = "private_personal",
    github_export: Annotated[bool, Form()] = False,
    status: Annotated[str, Form()] = "draft",
    approval_status: Annotated[str, Form()] = "draft",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    record = get_record(session, record_id)
    data = form_to_accomplishment(
        title,
        raw_note,
        action,
        metric,
        impact,
        supporting_narrative,
        date_started,
        date_completed,
        systems,
        technologies,
        tags,
        categories,
        sensitivity,
        github_export,
        status,
        approval_status,
    )
    accomplishments.update(session, record, data, "manually_edited")
    return redirect(f"/accomplishments/{record.id}")


@app.post("/accomplishments/{record_id}/archive")
def change_archive(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    archived: Annotated[bool, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    accomplishments.archive(session, get_record(session, record_id), archived)
    return redirect("/accomplishments")


@app.post("/accomplishments/{record_id}/delete")
def delete(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    accomplishments.soft_delete(session, get_record(session, record_id))
    return redirect("/accomplishments")


@app.get("/projects")
def projects_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    projects = list(session.scalars(select(Project).order_by(Project.name)))
    return templates.TemplateResponse("projects.html", context(request, projects=projects))


TAXONOMY_MODELS = {
    "category": Category,
    "tag": Tag,
    "technology": Technology,
    "skill": Skill,
    "competency": Competency,
}


@app.get("/taxonomy")
def taxonomy_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    items = {
        name: list(session.scalars(select(model).order_by(model.name)))
        for name, model in TAXONOMY_MODELS.items()
    }
    return templates.TemplateResponse("taxonomy.html", context(request, items=items))


@app.post("/taxonomy")
def create_taxonomy_item(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    name: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    model = TAXONOMY_MODELS.get(kind)
    if not model or not name.strip():
        raise HTTPException(status_code=400, detail="Choose a taxonomy type and provide a name.")
    if session.scalar(select(model).where(model.name == name.strip())):
        return redirect("/taxonomy")
    session.add(model(name=name.strip()))
    session.add(AuditEvent(event_type="taxonomy.created", metadata_json={"kind": kind}))
    session.commit()
    return redirect("/taxonomy")


@app.post("/projects")
def create_project(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if session.scalar(select(Project).where(Project.name == name.strip())):
        return templates.TemplateResponse(
            "projects.html",
            context(
                request,
                projects=list(session.scalars(select(Project))),
                error="Project name exists.",
            ),
            status_code=409,
        )
    project = Project(name=name.strip(), description=description.strip())
    session.add(project)
    session.add(AuditEvent(event_type="project.created", metadata_json={"name": project.name}))
    session.commit()
    return redirect("/projects")


@app.post("/accomplishments/{record_id}/evidence")
def add_evidence(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    reference_type: Annotated[str, Form()],
    reference_value: Annotated[str, Form()],
    notes: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    record = get_record(session, record_id)
    if not reference_value.strip():
        raise HTTPException(status_code=400, detail="Evidence value is required.")
    evidence = EvidenceReference(
        accomplishment_id=record.id,
        reference_type=reference_type.strip() or "other",
        reference_value=reference_value.strip(),
        notes=notes.strip(),
    )
    session.add(evidence)
    session.add(AuditEvent(event_type="evidence.created", metadata_json={"record_id": record.id}))
    session.commit()
    return redirect(f"/accomplishments/{record.id}")


@app.post("/accomplishments/{record_id}/attachments")
async def upload_attachment(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    attachment: UploadFile,
    sensitivity: Annotated[str, Form()] = "private_personal",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    record = get_record(session, record_id)
    if sensitivity not in {
        "public_safe",
        "private_personal",
        "internal",
        "confidential",
        "do_not_sync",
    }:
        raise HTTPException(status_code=400, detail="Unsupported attachment sensitivity.")
    original_name = Path(attachment.filename or "attachment").name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", original_name).strip(".-") or "attachment"
    content = await attachment.read(settings.max_attachment_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Attachment is empty.")
    if len(content) > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail="Attachment exceeds the configured size limit.")
    content_hash = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(AttachmentMetadata).where(
            AttachmentMetadata.accomplishment_id == record.id,
            AttachmentMetadata.content_hash == content_hash,
        )
    )
    if existing:
        return redirect(f"/accomplishments/{record.id}")
    storage = settings.data_dir / "attachments" / record.id
    storage.mkdir(parents=True, exist_ok=True)
    stored = storage / f"{content_hash[:16]}-{safe_stem}"
    stored.write_bytes(content)
    metadata = AttachmentMetadata(
        accomplishment_id=record.id,
        original_filename=original_name,
        stored_path=str(stored),
        content_hash=content_hash,
        sensitivity=sensitivity,
    )
    session.add(metadata)
    session.add(
        AuditEvent(
            event_type="attachment.uploaded",
            metadata_json={
                "record_id": record.id,
                "attachment_id": metadata.id,
                "bytes": len(content),
            },
        )
    )
    session.commit()
    return redirect(f"/accomplishments/{record.id}")


@app.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: str,
    request: Request,
    session: SessionDependency,
    _: User = Depends(current_user),
):
    metadata = session.get(AttachmentMetadata, attachment_id)
    stored = Path(metadata.stored_path) if metadata else None
    attachment_root = (settings.data_dir / "attachments").resolve()
    if (
        not metadata
        or not stored
        or not stored.is_file()
        or attachment_root not in stored.resolve().parents
    ):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    session.add(
        AuditEvent(event_type="attachment.downloaded", metadata_json={"attachment_id": metadata.id})
    )
    session.commit()
    return FileResponse(stored, filename=metadata.original_filename)


@app.get("/providers")
def providers_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    return templates.TemplateResponse(
        "providers.html",
        context(
            request,
            providers=list(session.scalars(select(AIProvider).order_by(AIProvider.priority))),
        ),
    )


@app.post("/providers")
def add_provider(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    base_url: Annotated[str, Form()],
    default_model: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    bearer_token: Annotated[str, Form()] = "",
    custom_headers: Annotated[str, Form()] = "",
    timeout_seconds: Annotated[int, Form()] = 60,
    retry_attempts: Annotated[int, Form()] = 1,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    try:
        headers = json.loads(custom_headers) if custom_headers.strip() else {}
        input_data = AIProviderInput(
            display_name=display_name,
            base_url=base_url,
            default_model=default_model,
            api_key=api_key,
            bearer_token=bearer_token,
            custom_headers=headers,
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
        )
        classification = classify_and_validate_url(input_data.base_url)
        provider = AIProvider(
            display_name=input_data.display_name,
            base_url=input_data.base_url,
            default_model=input_data.default_model,
            timeout_seconds=input_data.timeout_seconds,
            retry_attempts=input_data.retry_attempts,
            classification=classification,
            encrypted_api_key=encrypt_secret(input_data.api_key),
            encrypted_bearer_token=encrypt_secret(input_data.bearer_token),
            encrypted_headers=encrypt_secret(json.dumps(input_data.custom_headers)),
        )
        session.add(provider)
        session.add(
            AuditEvent(
                event_type="provider.created",
                metadata_json={"name": provider.display_name, "classification": classification},
            )
        )
        session.commit()
        return redirect("/providers")
    except (ValueError, ProviderSafetyError) as exc:
        return templates.TemplateResponse(
            "providers.html",
            context(request, providers=list(session.scalars(select(AIProvider))), error=str(exc)),
            status_code=400,
        )


@app.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="AI provider not found.")
    started = perf_counter()
    try:
        models = await list_models(provider)
        provider.last_test_at = datetime.now(UTC)
        provider.health_state = "healthy"
        session.add(
            AuditEvent(
                event_type="provider.tested",
                metadata_json={
                    "provider_id": provider.id,
                    "latency_ms": round((perf_counter() - started) * 1000),
                    "model_count": len(models),
                },
            )
        )
        session.commit()
        return templates.TemplateResponse(
            "providers.html",
            context(
                request,
                providers=list(session.scalars(select(AIProvider).order_by(AIProvider.priority))),
                models=models,
                message=f"Connection succeeded in {round((perf_counter() - started) * 1000)} ms.",
            ),
        )
    except Exception as exc:
        provider.last_test_at = datetime.now(UTC)
        provider.health_state = "failed"
        session.add(
            AuditEvent(
                event_type="provider.tested",
                outcome="failed",
                metadata_json={"provider_id": provider.id, "error_class": type(exc).__name__},
            )
        )
        session.commit()
        return templates.TemplateResponse(
            "providers.html",
            context(
                request,
                providers=list(session.scalars(select(AIProvider).order_by(AIProvider.priority))),
                error=f"Connection test failed: {type(exc).__name__}.",
            ),
            status_code=502,
        )


@app.post("/providers/{provider_id}/rotate-secrets")
def rotate_provider_secrets(
    provider_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    api_key: Annotated[str, Form()] = "",
    bearer_token: Annotated[str, Form()] = "",
    custom_headers: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="AI provider not found.")
    try:
        headers = json.loads(custom_headers) if custom_headers.strip() else {}
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        ):
            raise ValueError("Custom headers must be a JSON object with string values.")
        provider.encrypted_api_key = encrypt_secret(api_key)
        provider.encrypted_bearer_token = encrypt_secret(bearer_token)
        provider.encrypted_headers = encrypt_secret(json.dumps(headers))
    except (ValueError, json.JSONDecodeError) as exc:
        return templates.TemplateResponse(
            "providers.html",
            context(request, providers=list(session.scalars(select(AIProvider))), error=str(exc)),
            status_code=400,
        )
    session.add(
        AuditEvent(
            event_type="provider.secrets_rotated", metadata_json={"provider_id": provider.id}
        )
    )
    session.commit()
    return redirect("/providers")


@app.post("/providers/{provider_id}/delete")
def delete_provider(
    provider_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="AI provider not found.")
    session.add(
        AuditEvent(event_type="provider.deleted", metadata_json={"provider_id": provider.id})
    )
    session.delete(provider)
    session.commit()
    return redirect("/providers")


@app.get("/ai/draft/{record_id}")
async def ai_draft(
    record_id: str,
    request: Request,
    session: SessionDependency,
    provider_id: str,
    remote_confirmation: bool = False,
    _: User = Depends(current_user),
):
    record = get_record(session, record_id)
    provider = session.get(AIProvider, provider_id)
    if not provider or not provider.enabled:
        raise HTTPException(status_code=404, detail="AI provider not found.")
    transmission = {
        "raw_note": record.raw_note,
        "action": record.action,
        "metric": record.metric,
        "impact": record.impact,
        "systems": record.systems,
        "technologies": record.technologies,
        "tags": record.tags,
        "remote_confirmation": remote_confirmation,
    }
    if provider.classification == "remote" and not remote_confirmation:
        return templates.TemplateResponse(
            "remote_confirmation.html",
            context(
                request,
                record=record,
                provider=provider,
                transmission=json.dumps(transmission, indent=2),
            ),
        )
    try:
        draft = await generate_draft(provider, record.raw_note, transmission)
    except Exception as exc:
        session.add(
            AuditEvent(
                event_type="ai.generation",
                outcome="failed",
                metadata_json={
                    "record_id": record.id,
                    "provider_id": provider.id,
                    "error_class": type(exc).__name__,
                },
            )
        )
        session.commit()
        return templates.TemplateResponse(
            "detail.html",
            context(
                request,
                record=record,
                revisions=record.revisions,
                drafts=[],
                error=f"AI draft failed safely: {type(exc).__name__}. Your raw note remains saved.",
            ),
            status_code=502,
        )
    saved = AIDraft(
        accomplishment_id=record.id,
        provider_id=provider.id,
        model_name=provider.default_model,
        content=draft.model_dump(),
    )
    session.add(saved)
    session.add(
        AuditEvent(
            event_type="ai.generation",
            metadata_json={
                "record_id": record.id,
                "provider_id": provider.id,
                "classification": provider.classification,
            },
        )
    )
    session.commit()
    return templates.TemplateResponse(
        "ai_draft.html",
        context(request, record=record, provider=provider, draft=draft, draft_id=saved.id),
    )


@app.post("/ai/draft/{record_id}/approve")
def approve_ai_draft(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    draft_id: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    record = get_record(session, record_id)
    draft = session.get(AIDraft, draft_id)
    if not draft or draft.accomplishment_id != record.id:
        raise HTTPException(status_code=404, detail="Draft not found.")
    for field in (
        "title",
        "action",
        "metric",
        "impact",
        "supporting_narrative",
        "categories",
        "tags",
        "technologies",
    ):
        source = f"suggested_{field}" if field in {"categories", "tags", "technologies"} else field
        if source in draft.content:
            setattr(record, field, draft.content[source])
    record.status = "draft"
    record.approval_status = "draft"
    draft.status = "accepted"
    session.flush()
    accomplishments.record_revision(session, record, "ai_draft_accepted")
    session.add(
        AuditEvent(
            event_type="ai.draft_accepted",
            metadata_json={"record_id": record.id, "draft_id": draft.id},
        )
    )
    session.commit()
    return redirect(f"/accomplishments/{record.id}")


@app.post("/ai/draft/{record_id}/discard")
def discard_ai_draft(
    record_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    draft_id: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    record = get_record(session, record_id)
    draft = session.get(AIDraft, draft_id)
    if not draft or draft.accomplishment_id != record.id:
        raise HTTPException(status_code=404, detail="Draft not found.")
    draft.status = "discarded"
    session.add(
        AuditEvent(
            event_type="ai.draft_discarded",
            metadata_json={"record_id": record.id, "draft_id": draft.id},
        )
    )
    session.commit()
    return redirect(f"/accomplishments/{record.id}")


@app.get("/reports")
def reports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    records = accomplishments.search(session)
    templates_list = list(session.scalars(select(ReportTemplate).order_by(ReportTemplate.name)))
    reports = list(session.scalars(select(Report).order_by(Report.created_at.desc())))
    return templates.TemplateResponse(
        "reports.html", context(request, records=records, templates=templates_list, reports=reports)
    )


@app.post("/reports/templates")
def create_report_template(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    name: Annotated[str, Form()],
    content: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Template name is required.")
    if session.scalar(select(ReportTemplate).where(ReportTemplate.name == name.strip())):
        raise HTTPException(
            status_code=409, detail="A report template with that name already exists."
        )
    template = ReportTemplate(name=name.strip(), content=content.strip())
    session.add(template)
    session.add(
        AuditEvent(event_type="report_template.created", metadata_json={"template_id": template.id})
    )
    session.commit()
    return redirect("/reports")


@app.post("/reports")
def create_report(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    title: Annotated[str, Form()],
    record_ids: Annotated[list[str] | None, Form()] = None,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    records = [get_record(session, record_id) for record_id in record_ids or []]
    if not records:
        return templates.TemplateResponse(
            "reports.html",
            context(
                request,
                records=accomplishments.search(session),
                error="Select at least one accomplishment.",
            ),
            status_code=400,
        )
    report = generate_docx(session, title.strip() or "CareerForge report", records)
    return redirect(f"/reports/{report.id}/download")


@app.get("/reports/{report_id}")
def report_detail(
    report_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    report = session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    items = list(
        session.scalars(
            select(ReportItem)
            .where(ReportItem.report_id == report.id)
            .order_by(ReportItem.position, ReportItem.id)
        )
    )
    return templates.TemplateResponse(
        "report_detail.html", context(request, report=report, items=items)
    )


@app.post("/reports/{report_id}/reorder")
async def reorder_report_items(
    report_id: str,
    request: Request,
    session: SessionDependency,
    current: User = Depends(current_user),
):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    report = session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    items = list(session.scalars(select(ReportItem).where(ReportItem.report_id == report.id)))
    item_map = {item.id: item for item in items}
    try:
        requested = sorted(
            (
                (item_id.removeprefix("position_"), int(value))
                for item_id, value in form.items()
                if item_id.startswith("position_") and isinstance(value, str)
            ),
            key=lambda pair: pair[1],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Positions must be whole numbers.") from exc
    if {item_id for item_id, _ in requested} != set(item_map):
        raise HTTPException(status_code=400, detail="Report item selection is invalid.")
    for position, (item_id, _) in enumerate(requested, start=1):
        item_map[item_id].position = position
    session.add(
        AuditEvent(event_type="report.items_reordered", metadata_json={"report_id": report.id})
    )
    session.commit()
    return redirect(f"/reports/{report.id}")


@app.get("/reports/{report_id}/download")
def download_report(
    report_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    report = session.get(Report, report_id)
    if not report or not Path(report.output_path).is_file():
        raise HTTPException(status_code=404, detail="Report file not found.")
    return FileResponse(
        report.output_path,
        filename=Path(report.output_path).name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/exports")
def exports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    profiles = list(
        session.scalars(select(GitRepositoryProfile).order_by(GitRepositoryProfile.name))
    )
    return templates.TemplateResponse("exports.html", context(request, profiles=profiles))


@app.post("/exports/profiles")
def create_export_profile(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    name: Annotated[str, Form()],
    repository_path: Annotated[str, Form()],
    branch: Annotated[str, Form()] = "main",
    export_subdirectory: Annotated[str, Form()] = "accomplishments",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    path = Path(repository_path).expanduser().resolve()
    if not name.strip() or not path.is_dir():
        raise HTTPException(
            status_code=400, detail="Provide a profile name and an existing repository directory."
        )
    if Path(export_subdirectory).is_absolute() or ".." in Path(export_subdirectory).parts:
        raise HTTPException(
            status_code=400,
            detail="Export subdirectory must be a relative path inside the repository.",
        )
    try:
        git_ops.status(path)
    except git_ops.GitOperationError as exc:
        raise HTTPException(
            status_code=400, detail="The selected path is not a healthy Git repository."
        ) from exc
    if session.scalar(
        select(GitRepositoryProfile).where(GitRepositoryProfile.name == name.strip())
    ):
        raise HTTPException(
            status_code=409, detail="An export profile with that name already exists."
        )
    profile = GitRepositoryProfile(
        name=name.strip(),
        repository_path=str(path),
        branch=branch.strip() or "main",
        export_subdirectory=export_subdirectory.strip() or "accomplishments",
    )
    session.add(profile)
    session.add(
        AuditEvent(event_type="git_profile.created", metadata_json={"profile_id": profile.id})
    )
    session.commit()
    return redirect("/exports")


@app.get("/exports/{profile_id}/preview")
def export_preview(
    profile_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    profile = session.get(GitRepositoryProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Export profile not found.")
    try:
        repo_status = git_ops.status(Path(profile.repository_path))
        repo_diff = git_ops.diff(Path(profile.repository_path))
    except git_ops.GitOperationError as exc:
        return templates.TemplateResponse(
            "exports.html",
            context(
                request,
                profiles=list(session.scalars(select(GitRepositoryProfile))),
                error=f"Git preview failed: {exc}",
            ),
            status_code=400,
        )
    manifest = export_markdown(
        session, Path(profile.repository_path) / profile.export_subdirectory, dry_run=True
    )
    return templates.TemplateResponse(
        "exports.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            active_profile=profile,
            manifest=manifest,
            repo_status=repo_status,
            repo_diff=repo_diff,
        ),
    )


@app.post("/exports/dry-run")
def export_dry_run(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    manifest = export_markdown(session, settings.data_dir / "temp" / "dry-run", dry_run=True)
    return templates.TemplateResponse(
        "exports.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            manifest=manifest,
        ),
    )


@app.post("/exports/{profile_id}/apply")
def apply_export(
    profile_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "EXPORT":
        raise HTTPException(
            status_code=400,
            detail="Type EXPORT to write Markdown files to the selected repository.",
        )
    profile = session.get(GitRepositoryProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Export profile not found.")
    manifest = export_markdown(
        session, Path(profile.repository_path) / profile.export_subdirectory, dry_run=False
    )
    files_value = manifest.get("files")
    file_count = len(files_value) if isinstance(files_value, list) else 0
    session.add(
        AuditEvent(
            event_type="git_export.applied",
            metadata_json={"profile_id": profile.id, "count": file_count},
        )
    )
    session.commit()
    return templates.TemplateResponse(
        "exports.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            active_profile=profile,
            manifest=manifest,
            message="Markdown files were written. Review the Git preview before staging or committing.",
        ),
    )


@app.get("/audit")
def audit(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    events = list(
        session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100))
    )
    return templates.TemplateResponse("audit.html", context(request, events=events))


@app.get("/imports")
def imports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    runs = list(session.scalars(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(100)))
    return templates.TemplateResponse("imports.html", context(request, runs=runs))


@app.get("/operations")
def operations_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    backups = sorted((settings.data_dir / "backups").glob("CareerForge-*.zip"), reverse=True)
    return templates.TemplateResponse("operations.html", context(request, backups=backups))


@app.post("/operations/backup")
def create_local_backup(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "BACKUP":
        raise HTTPException(status_code=400, detail="Type BACKUP to create a local archive.")
    try:
        archive = create_backup(settings.data_dir)
        members = validate_backup_archive(archive)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            event_type="backup.created",
            metadata_json={"filename": archive.name, "member_count": len(members)},
        )
    )
    session.commit()
    return templates.TemplateResponse(
        "operations.html",
        context(
            request,
            backups=sorted((settings.data_dir / "backups").glob("CareerForge-*.zip"), reverse=True),
            message=f"Backup created and validated: {archive.name}",
        ),
    )


@app.post("/imports/odt")
def import_odt_source(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    source_path: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "IMPORT":
        raise HTTPException(status_code=400, detail="Type IMPORT to read the selected ODT source.")
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".odt" or not source.is_file():
        raise HTTPException(status_code=400, detail="Provide an existing local .odt file.")
    run = import_odt(session, source)
    return templates.TemplateResponse(
        "imports.html",
        context(
            request,
            runs=list(
                session.scalars(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(100))
            ),
            message=f"Import status: {run.status}; records added: {run.imported_count}.",
        ),
    )
