from __future__ import annotations

import json
import secrets
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
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
    AuditEvent,
    EvidenceReference,
    Project,
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
from app.services import accomplishments
from app.services.ai import (
    ProviderSafetyError,
    classify_and_validate_url,
    generate_draft,
)
from app.services.exporter import export_markdown
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
):
    return templates.TemplateResponse(
        "accomplishments.html",
        context(
            request,
            records=accomplishments.search(session, q, archived),
            query=q,
            archived=archived,
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
        ),
    )


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
        )
        classification = classify_and_validate_url(input_data.base_url)
        provider = AIProvider(
            display_name=input_data.display_name,
            base_url=input_data.base_url,
            default_model=input_data.default_model,
            timeout_seconds=input_data.timeout_seconds,
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


@app.get("/reports")
def reports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    records = accomplishments.search(session)
    return templates.TemplateResponse("reports.html", context(request, records=records))


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


@app.get("/reports/{report_id}/download")
def download_report(
    report_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    from app.models import Report

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
    return templates.TemplateResponse("exports.html", context(request))


@app.post("/exports/dry-run")
def export_dry_run(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    manifest = export_markdown(session, settings.data_dir / "temp" / "dry-run", dry_run=True)
    return templates.TemplateResponse("exports.html", context(request, manifest=manifest))


@app.get("/audit")
def audit(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    events = list(
        session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100))
    )
    return templates.TemplateResponse("audit.html", context(request, events=events))
