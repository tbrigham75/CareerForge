from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import logging
import math
import re
import secrets
import sqlite3
import subprocess
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Annotated
from urllib.parse import quote
from zoneinfo import available_timezones

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import SessionLocal, get_session
from app.models import (
    Accomplishment,
    AIDraft,
    AIProvider,
    AttachmentMetadata,
    AuditEvent,
    EvidenceReference,
    ExportRun,
    GitRepositoryProfile,
    ImportRun,
    PendingFileDeletion,
    Project,
    Report,
    ReportingSettings,
    ReportItem,
    ReportTemplate,
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
from app.services import (
    accomplishments,
    database_maintenance,
    document_exports,
    git_ops,
    native_picker,
    reporting_year,
    taxonomy,
    trash,
)
from app.services.ai import (
    ProviderSafetyError,
    classify_and_validate_url,
    generate_draft,
    list_models,
)
from app.services.backup import BackupError, create_backup, validate_backup_archive
from app.services.exporter import export_markdown
from app.services.file_browser import browse_paths
from app.services.importer import import_odt
from app.services.reports import generate_docx, regenerate_docx

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def run_trash_maintenance() -> None:
    try:
        with SessionLocal() as session:
            trash.maintenance(session)
    except Exception:
        logging.getLogger(__name__).exception("Trash maintenance failed; will retry next hour")


@asynccontextmanager
async def lifespan(application: FastAPI):
    stopped = asyncio.Event()

    async def maintain():
        while not stopped.is_set():
            await asyncio.to_thread(run_trash_maintenance)
            with suppress(TimeoutError):
                await asyncio.wait_for(stopped.wait(), timeout=3600)

    task = asyncio.create_task(maintain())
    try:
        yield
    finally:
        stopped.set()
        await task


app = FastAPI(title="CareerForge", docs_url=None, redoc_url=None, lifespan=lifespan)
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
        "max_attachment_bytes": settings.max_attachment_bytes,
        "today": date.today().isoformat(),
        **values,
    }


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@app.exception_handler(HTTPException)
async def user_facing_http_error(request: Request, exc: HTTPException):
    """Keep the local browser application in its UI for expected request errors."""
    if exc.status_code == 401:
        request.session.clear()
        return redirect("/login")
    return templates.TemplateResponse(
        "error.html",
        context(request, error=str(exc.detail), status_code=exc.status_code),
        status_code=exc.status_code,
    )


def current_user(request: Request, session: SessionDependency) -> User:
    user_id = require_authenticated(request)
    user = session.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@app.post("/files/browse")
def browse_local_files(
    request: Request,
    csrf: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    path: Annotated[str, Form()] = "",
    repository: Annotated[str, Form()] = "",
    select_path: Annotated[bool, Form()] = False,
    offset: Annotated[int, Form()] = 0,
    show_hidden: Annotated[bool, Form()] = False,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    try:
        if kind == "subdirectory" and not repository.strip():
            raise ValueError("Choose a repository folder first.")
        return browse_paths(kind, path, repository, select_path, offset, show_hidden)
    except git_ops.GitOperationError:
        return JSONResponse(
            {"error": "This folder is not a usable Git repository."}, status_code=400
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return JSONResponse(
            {"error": "This location is unavailable or you do not have permission to browse it."},
            status_code=400,
        )


@app.get("/files/picker-capabilities")
def picker_capabilities(request: Request, _: User = Depends(current_user)):
    return {"native": native_picker.available(request)}


@app.post("/files/pick-native")
def pick_native(
    request: Request,
    csrf: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    path: Annotated[str, Form()] = "",
    repository: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if not native_picker.available(request):
        return JSONResponse(
            {
                "error": "Windows dialogs require a browser connected directly to localhost on the Windows desktop running CareerForge."
            },
            status_code=403,
        )
    try:
        return native_picker.choose(kind, path, repository)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"error": "The Windows picker timed out. Your selection is unchanged; browse again."},
            status_code=408,
        )
    except (ValueError, OSError, RuntimeError, git_ops.GitOperationError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


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
    started = parse_date(date_started)
    completed = parse_date(date_completed)
    if started and completed and started > completed:
        raise ValueError("Start date must be on or before completion date.")

    return AccomplishmentInput(
        title=title,
        raw_note=raw_note,
        action=action,
        metric=metric,
        impact=impact,
        supporting_narrative=supporting_narrative,
        date_started=started,
        date_completed=completed,
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
    period = reporting_year.current_period(reporting_year.preferences(session))
    recent = reporting_year.current_records(accomplishments.search(session), period)[:8]
    count = (
        session.scalar(
            select(func.count())
            .select_from(Accomplishment)
            .where(Accomplishment.deleted_at.is_(None))
        )
        or 0
    )
    return templates.TemplateResponse(
        "dashboard.html", context(request, recent=recent, count=count, period=period)
    )


@app.get("/capture")
def capture_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    providers = list(session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True))))
    projects = list(session.scalars(select(Project).order_by(Project.name)))
    return templates.TemplateResponse(
        "capture.html", context(request, providers=providers, projects=projects, record=None)
    )


@app.post("/capture/assist")
async def assist_capture(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    raw_note: Annotated[str, Form()] = "",
    follow_up_answers: Annotated[str, Form()] = "",
    target_field: Annotated[str, Form()] = "",
    target_answer: Annotated[str, Form()] = "",
    target_question: Annotated[str, Form()] = "",
    provider_id: Annotated[str, Form()] = "",
    remote_confirmation: Annotated[bool, Form()] = False,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    provider = session.get(AIProvider, provider_id) if provider_id else None
    if not provider or not provider.enabled:
        return JSONResponse(
            {"error": "Set up an enabled AI provider first.", "setup_url": "/providers"},
            status_code=400,
        )
    if not provider.default_model.strip():
        return JSONResponse(
            {
                "error": "Set a default model for this provider on AI Providers.",
                "setup_url": "/providers",
            },
            status_code=400,
        )
    if not raw_note.strip() or len(raw_note) > 20_000:
        return JSONResponse(
            {"error": "Enter a note between 1 and 20,000 characters."}, status_code=400
        )
    if len(follow_up_answers) > 20_000:
        return JSONResponse(
            {"error": "Keep follow-up answers under 20,000 characters."}, status_code=400
        )
    if target_field and (
        target_field not in {"metric", "impact"}
        or not target_answer.strip()
        or len(target_answer) > 10_000
        or len(target_question) > 10_000
    ):
        return JSONResponse(
            {"error": "Choose Metric or Impact and provide an answer of up to 10,000 characters."},
            status_code=400,
        )
    if target_field:
        follow_up_answers = (
            f"Field: {target_field}\nQuestion: {target_question}\nAnswer: {target_answer}"
        )
    try:
        classification = classify_and_validate_url(provider.base_url)
        if classification == "remote" and not remote_confirmation:
            return {
                "confirmation_required": True,
                "provider": provider.display_name,
                "raw_note": raw_note,
                "follow_up_answers": follow_up_answers,
            }
        draft = await generate_draft(
            provider,
            raw_note,
            {
                "remote_confirmation": remote_confirmation,
                "follow_up_answers": follow_up_answers,
                "target_field": target_field,
            },
        )
    except Exception:
        return JSONResponse(
            {
                "error": "AI assistance failed. Check the provider connection and default model, then retry. Your form has not been changed."
            },
            status_code=502,
        )
    values = draft.model_dump()
    if target_field:
        suggestion = values[target_field].strip()
        if (
            not suggestion
            or len(suggestion) > 20_000
            or re.search(
                r"\[|missing.information|more information needed|quantitative measure not provided",
                suggestion,
                re.I,
            )
        ):
            return JSONResponse(
                {
                    "error": f"The AI did not return usable wording for {target_field.title()}. Your answer and existing fields are unchanged. Please retry."
                },
                status_code=502,
            )
        return {"field": target_field, "suggestion": suggestion}
    # Capture coaching focuses on missing deliverables, not generic model curiosity.
    values["questions"] = []
    # Missing-field prompts are rendered beside the fields; do not reintroduce
    # unrelated model questions through a second generic placeholder list.
    values["placeholders"] = []
    field_questions = {}
    subject = " ".join(raw_note.split())[:180]
    for field, fallback in {
        "metric": f'For this work ("{subject}"), what count, scope, frequency, or measured before-and-after result can you confirm?',
        "impact": f'For this work ("{subject}"), what changed for the people or systems involved—what became possible, easier, or more reliable?',
    }.items():
        value = values[field].strip()
        missing = not value or bool(
            re.search(
                r"\[|missing.information|not (?:provided|specified|available)|more information needed|unknown|\btbd\b",
                value,
                re.I,
            )
        )
        if missing:
            field_questions[field] = values.get(f"{field}_question", "").strip() or fallback
    values["field_questions"] = field_questions
    for field, question in {
        "action": "What did you do?",
        "metric": "What measurable result or scope can you confirm?",
        "impact": "What outcome can you confirm?",
    }.items():
        if not values[field].strip():
            values[field] = "[More information needed]"
            if field == "action":
                values["questions"].append(question)
    return {"draft": values}


@app.post("/capture")
async def capture(
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
    attachment: UploadFile | None = None,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    submitted = await request.form()
    form_values = {key: value for key, value in submitted.items() if isinstance(value, str)}
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
                form_values=form_values,
                error="Enter a raw note or accomplishment content.",
            ),
            status_code=400,
        )
    status = "raw_note" if action_choice == "raw" else "completed"
    approval = "draft" if action_choice == "raw" else "approved"
    try:
        project = session.get(Project, project_id) if project_id else None
        if project_id and project is None:
            raise ValueError("The selected project no longer exists. Choose another project.")
        if status == "completed" and project is None:
            raise ValueError(
                "Select a project before saving a completed accomplishment. You can save a raw note without a project."
            )
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
    except ValueError as exc:
        providers = list(session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True))))
        projects = list(session.scalars(select(Project).order_by(Project.name)))
        return templates.TemplateResponse(
            "capture.html",
            context(
                request,
                providers=providers,
                projects=projects,
                record=None,
                form_values=form_values,
                error=str(exc),
            ),
            status_code=400,
        )
    content = None
    if attachment and attachment.filename:
        try:
            content = await read_attachment(attachment)
        except HTTPException as exc:
            return templates.TemplateResponse(
                "capture.html",
                context(
                    request,
                    providers=list(
                        session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True)))
                    ),
                    projects=list(session.scalars(select(Project).order_by(Project.name))),
                    record=None,
                    form_values=form_values,
                    error=f"{exc.detail} Your text is preserved. Choose another file or clear the selection and save again.",
                ),
                status_code=exc.status_code,
            )
    record = accomplishments.create(session, data, commit=False)
    stored = None
    try:
        if project:
            record.projects.append(project)
            session.add(
                AuditEvent(
                    event_type="accomplishment.project_linked",
                    metadata_json={"record_id": record.id, "project_id": project.id},
                )
            )
        if content is not None and attachment:
            stored = store_attachment(
                session, record, attachment.filename or "attachment", content, sensitivity
            )
        session.commit()
    except Exception:
        session.rollback()
        if stored:
            stored.unlink(missing_ok=True)
        raise
    if action_choice == "draft" and provider_id:
        return redirect(f"/ai/draft/{record.id}?provider_id={provider_id}")
    return redirect(f"/accomplishments/{record.id}")


@app.get("/capture/projects")
def capture_project_options(session: SessionDependency, _: User = Depends(current_user)):
    return {
        "projects": [
            {"id": item.id, "name": item.name}
            for item in session.scalars(select(Project).order_by(Project.name))
        ]
    }


@app.get("/accomplishments")
@app.get("/history")
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
    scope: str = "current",
    year: str = "",
):
    if scope not in {"current", "all"}:
        raise HTTPException(400, "Choose Current reporting year or All years.")
    preference = reporting_year.preferences(session)
    period = reporting_year.current_period(preference)
    history = request.url.path == "/history"
    all_records = accomplishments.search(session, include_archived=True)
    periods = {
        reporting_year.period_for(record.date_completed, preference)
        for record in reporting_year.historical_records(all_records, period)
        if record.date_completed is not None
    }
    years = sorted(periods, key=lambda item: item.start, reverse=True)
    selected = next((item for item in years if item.start.isoformat() == year), None)
    if history and year and selected is None:
        raise HTTPException(400, "Choose an available historical reporting year.")
    records = accomplishments.search(
        session,
        q,
        archived,
        parse_date(date_from),
        parse_date(date_to),
        sensitivity,
        tag,
        technology,
        project_id,
    )
    if history:
        records = reporting_year.historical_records(records, period)
        if selected:
            records = [
                record
                for record in records
                if record.date_completed is not None
                and selected.start <= record.date_completed <= selected.end
            ]
    elif scope == "current":
        records = reporting_year.current_records(records, period)
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
            records=records,
            history=history,
            period=period,
            years=years,
            year=year,
            scope=scope,
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
    try:
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
    except ValueError as exc:
        return templates.TemplateResponse(
            "edit_accomplishment.html",
            context(request, record=record, error=str(exc)),
            status_code=400,
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
    return templates.TemplateResponse(
        "projects.html",
        context(
            request,
            projects=projects,
            message="Project updated." if request.query_params.get("saved") == "1" else None,
        ),
    )


@app.get("/projects/{project_id}/edit")
def edit_project_page(
    project_id: str, request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    return templates.TemplateResponse(
        "project_edit.html",
        context(
            request,
            project=project,
            values={"name": project.name, "description": project.description},
        ),
    )


@app.post("/projects/{project_id}/edit")
def edit_project(
    project_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    name, description = name.strip(), description.strip()
    error = None
    status = 400
    if not name or len(name) > 200 or len(description) > 10000:
        error = "Provide a project name (up to 200 characters) and a description up to 10,000 characters."
    elif session.scalar(
        select(Project).where(Project.id != project.id, func.lower(Project.name) == name.lower())
    ):
        error, status = "Another project already uses that name.", 409
    else:
        project.name, project.description = name, description
        session.add(AuditEvent(event_type="project.updated", metadata_json={"id": project.id}))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            error, status = "Another project already uses that name.", 409
    if error:
        return templates.TemplateResponse(
            "project_edit.html",
            context(
                request,
                project=project,
                values={"name": name, "description": description},
                error=error,
            ),
            status_code=status,
        )
    return redirect("/projects?saved=1")


def reporting_settings_view(request: Request, preference: ReportingSettings, **values: object):
    return templates.TemplateResponse(
        "reporting_year.html",
        context(
            request,
            preference=preference,
            period=reporting_year.current_period(preference),
            months=list(calendar.month_name)[1:],
            timezones=sorted(available_timezones()),
            **values,
        ),
    )


@app.get("/reporting-year")
def reporting_settings_page(
    request: Request, session: SessionDependency, _: User = Depends(current_user)
):
    return reporting_settings_view(
        request,
        reporting_year.preferences(session),
        message="Reporting settings saved. Records have been regrouped without changing their content."
        if request.query_params.get("saved") == "1"
        else None,
    )


@app.post("/reporting-year")
def save_reporting_settings(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    mode: Annotated[str, Form()],
    start_month: Annotated[int, Form()],
    year_naming: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    action: Annotated[str, Form()] = "save",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    try:
        reporting_year.validate(mode, start_month, year_naming, timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if action not in {"save", "preview"}:
        raise HTTPException(400, "Unknown reporting settings action.")
    preference = ReportingSettings(
        id=1, mode=mode, start_month=start_month, year_naming=year_naming, timezone=timezone
    )
    if action == "preview":
        return reporting_settings_view(request, preference, preview=True)
    session.merge(preference)
    session.add(
        AuditEvent(
            event_type="reporting_year.updated",
            metadata_json={
                "mode": mode,
                "start_month": start_month,
                "year_naming": year_naming,
                "timezone": timezone,
            },
        )
    )
    session.commit()
    return redirect("/reporting-year?saved=1")


def database_view(request: Request, session: Session, **values: object):
    return templates.TemplateResponse(
        "database.html",
        context(
            request,
            storage=database_maintenance.storage_summary(),
            trash_count=session.scalar(
                select(func.count())
                .select_from(Accomplishment)
                .where(Accomplishment.deleted_at.is_not(None))
            ),
            pending_count=session.scalar(select(func.count()).select_from(PendingFileDeletion)),
            **values,
        ),
    )


@app.get("/database")
def database_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    return database_view(request, session, message=request.session.pop("database_message", None))


@app.post("/database/{action}")
def database_action(
    action: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if action not in {"check", "cleanup", "compact"}:
        raise HTTPException(404, "Unknown maintenance action.")
    if action == "compact" and confirmation != "COMPACT":
        raise HTTPException(400, "Type COMPACT to confirm database compaction.")
    try:
        if action == "check":
            return database_view(request, session, health=database_maintenance.check_health())
        if action == "cleanup":
            with trash.lock:
                trash.cleanup_files(session)
            message = "File cleanup retried. See Trash for any remaining errors."
        else:
            # Release this request's read transaction before SQLite acquires its write lock.
            session.commit()
            backup = database_maintenance.compact_database()
            message = f"Database compacted. Database-only backup saved: {backup.name}"
        session.add(AuditEvent(event_type=f"database.{action}", metadata_json={}))
        session.commit()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logging.getLogger(__name__).exception("Database maintenance failed")
        raise HTTPException(
            503,
            "Maintenance could not finish. The database may be busy, or storage unavailable. No automatic repair was attempted. Check server logs and retry after other work finishes.",
        ) from exc
    request.session["database_message"] = message
    return redirect("/database")


@app.get("/trash")
def trash_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    records = list(
        session.scalars(
            select(Accomplishment)
            .where(Accomplishment.deleted_at.is_not(None))
            .order_by(Accomplishment.deleted_at.desc())
        )
    )
    now = datetime.now(UTC)
    items = []
    for record in records:
        assert record.deleted_at is not None
        expires = record.deleted_at.replace(tzinfo=UTC) + timedelta(days=trash.RETENTION_DAYS)
        items.append(
            {
                "record": record,
                "expires": expires,
                "days": max(0, math.ceil((expires - now).total_seconds() / 86400)),
            }
        )
    pending = list(session.scalars(select(PendingFileDeletion)))
    messages = {
        "restored": "Accomplishment restored to its previous active or archived state.",
        "deleted": "Permanent deletion completed. Any pending file cleanup is shown below.",
        "cleaned": "Cleanup retried. Remaining issues are shown below.",
    }
    return templates.TemplateResponse(
        "trash.html",
        context(
            request,
            items=items,
            pending=pending,
            message=messages.get(request.query_params.get("result", "")),
        ),
    )


@app.post("/trash/cleanup")
def retry_trash_cleanup(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    with trash.lock:
        trash.cleanup_files(session)
    return redirect("/trash?result=cleaned")


@app.post("/trash/empty")
def empty_trash(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "EMPTY TRASH":
        raise HTTPException(400, "Type EMPTY TRASH to confirm permanent deletion.")
    with trash.lock:
        trash.purge(
            session,
            list(
                session.scalars(
                    select(Accomplishment).where(Accomplishment.deleted_at.is_not(None))
                )
            ),
        )
    return redirect("/trash?result=deleted")


@app.post("/trash/{record_id}/{action}")
def change_trash(
    record_id: str,
    action: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    with trash.lock:
        record = session.get(Accomplishment, record_id)
        if not record or record.deleted_at is None:
            raise HTTPException(404, "This item is no longer in Trash.")
        if action == "restore":
            trash.restore(session, record)
            return redirect("/trash?result=restored")
        if action != "delete":
            raise HTTPException(404, "Unknown Trash action.")
        if confirmation != "DELETE":
            raise HTTPException(400, "Type DELETE to confirm permanent deletion.")
        trash.purge(session, [record])
    return redirect("/trash?result=deleted")


TAXONOMY_MODELS = taxonomy.GROUPS


@app.get("/taxonomy")
def taxonomy_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    items = {
        name: list(
            {
                entry.name.strip().casefold(): entry
                for entry in session.scalars(select(model).order_by(model.name.desc()))
            }.values()
        )[::-1]
        for name, model in TAXONOMY_MODELS.items()
    }
    return templates.TemplateResponse("taxonomy.html", context(request, items=items))


@app.get("/taxonomy/suggestions")
def taxonomy_suggestions(session: SessionDependency, _: User = Depends(current_user)):
    return taxonomy.suggestions(session)


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
    try:
        taxonomy.register(session, model, [name])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    if not name.strip() or len(name.strip()) > 200 or len(description.strip()) > 10000:
        raise HTTPException(
            400,
            "Provide a project name up to 200 characters and description up to 10,000 characters.",
        )
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
    content = await read_attachment(attachment)
    stored = store_attachment(
        session, record, attachment.filename or "attachment", content, sensitivity
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        if stored:
            stored.unlink(missing_ok=True)
        raise
    return redirect(f"/accomplishments/{record.id}")


async def read_attachment(attachment: UploadFile) -> bytes:
    content = await attachment.read(settings.max_attachment_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Attachment is empty.")
    if len(content) > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail="Attachment exceeds the configured size limit.")
    return content


def store_attachment(
    session: Session, record: Accomplishment, filename: str, content: bytes, sensitivity: str
) -> Path | None:
    original_name = Path(filename.replace("\\", "/")).name[:300] or "attachment"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", original_name).strip(".-")[:160] or "attachment"
    content_hash = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(AttachmentMetadata).where(
            AttachmentMetadata.accomplishment_id == record.id,
            AttachmentMetadata.content_hash == content_hash,
        )
    )
    if existing:
        return None
    storage = settings.data_dir / "attachments" / record.id
    storage.mkdir(parents=True, exist_ok=True)
    stored = storage / f"{content_hash[:16]}-{safe_stem}"
    metadata = AttachmentMetadata(
        accomplishment_id=record.id,
        original_filename=original_name,
        stored_path=str(stored),
        content_hash=content_hash,
        sensitivity=sensitivity,
    )
    session.add(metadata)
    session.flush()
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
    try:
        stored.write_bytes(content)
    except OSError:
        stored.unlink(missing_ok=True)
        raise
    return stored


@app.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: str,
    request: Request,
    session: SessionDependency,
    _: User = Depends(current_user),
):
    metadata = session.get(AttachmentMetadata, attachment_id)
    if metadata and metadata.accomplishment_id:
        get_record(session, metadata.accomplishment_id)
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


def report_page_response(
    request: Request, session: Session, values=None, selected=None, error="", status_code=200
):
    records = [record for record in accomplishments.search(session) if record.report_inclusion]
    templates_list = list(session.scalars(select(ReportTemplate).order_by(ReportTemplate.name)))
    reports = list(session.scalars(select(Report).order_by(Report.created_at.desc())))
    defaults = {
        "title": f"Accomplishments — {date.today().isoformat()}",
        "content": "",
        "report_type": "custom",
        "output_filename": f"accomplishments-{date.today().isoformat()}.docx",
        "layout": "detailed",
        "template_id": "",
        "query": "",
        "date_from": "",
        "date_to": "",
    }
    defaults.update(values or {})
    return templates.TemplateResponse(
        "reports.html",
        context(
            request,
            records=records,
            templates=templates_list,
            reports=reports,
            values=defaults,
            selected=selected,
            error=error,
            template_data={
                item.id: {"name": item.name, "settings": item.settings or {"content": item.content}}
                for item in templates_list
            },
            report_directory=str(settings.data_dir / "reports"),
        ),
        status_code=status_code,
    )


@app.get("/reports")
def reports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    values = {
        key: request.query_params[key]
        for key in ("query", "date_from", "date_to")
        if key in request.query_params
    }
    return report_page_response(request, session, values)


def reusable_report_settings(values) -> dict[str, str]:
    result = {
        key: str(values[key]).strip()
        for key in ("title", "content", "report_type", "output_filename", "layout")
        if key in values
    }
    if "title" in result and (not result["title"] or len(result["title"]) > 300):
        raise ValueError("Enter a report title of 1–300 characters.")
    if len(result.get("content", "")) > 20000:
        raise ValueError("Keep report notes under 20,000 characters.")
    if result.get("layout", "detailed") not in {"detailed", "impact_first", "compact"}:
        raise ValueError("Choose a supported report layout.")
    if result.get("report_type", "custom") not in {"custom", "monthly", "quarterly", "annual"}:
        raise ValueError("Choose a supported report type.")
    filename = result.get("output_filename")
    if filename is not None and (
        not filename
        or len(filename) > 180
        or re.search(r'[\\/:*?"<>|\x00-\x1f]', filename)
        or not filename.lower().endswith(".docx")
    ):
        raise ValueError(
            "Enter a filename ending in .docx, without folder paths or special filename characters."
        )
    return result


@app.post("/reports/templates")
@app.post("/reports/templates/{template_id}/update")
async def create_report_template(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    name: Annotated[str, Form()],
    content: Annotated[str, Form()] = "",
    template_id: str = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if not name.strip() or len(name.strip()) > 150:
        return JSONResponse(
            {"error": "Enter a template name of 1–150 characters."}, status_code=400
        )
    existing = list(session.scalars(select(ReportTemplate)))
    if any(
        item.id != template_id and item.name.casefold() == name.strip().casefold()
        for item in existing
    ):
        return JSONResponse({"error": "A template with that name already exists."}, status_code=409)
    try:
        saved_settings = reusable_report_settings(await request.form())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    template = session.get(ReportTemplate, template_id) if template_id else ReportTemplate()
    if template is None:
        return JSONResponse({"error": "Template no longer exists."}, status_code=404)
    template.name = name.strip()
    template.content = content.strip()
    template.settings = saved_settings
    session.add(template)
    session.flush()
    session.add(
        AuditEvent(
            event_type="report_template.updated" if template_id else "report_template.created",
            metadata_json={"template_id": template.id},
        )
    )
    session.commit()
    if "application/json" in request.headers.get("accept", ""):
        return {"id": template.id, "name": template.name, "settings": template.settings}
    return redirect("/reports")


@app.post("/reports/templates/{template_id}/delete")
def delete_report_template(
    template_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    template = session.get(ReportTemplate, template_id)
    if not template:
        return JSONResponse({"error": "Template no longer exists."}, status_code=404)
    session.delete(template)
    session.add(
        AuditEvent(event_type="report_template.deleted", metadata_json={"template_id": template_id})
    )
    session.commit()
    return {"deleted": template_id}


@app.post("/reports")
async def create_report(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    title: Annotated[str, Form()],
    record_ids: Annotated[list[str] | None, Form()] = None,
    template_id: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    form = await request.form()
    values = {
        key: str(form[key])
        for key in (
            "title",
            "content",
            "report_type",
            "output_filename",
            "layout",
            "template_id",
            "query",
            "date_from",
            "date_to",
        )
        if key in form
    }
    selected = list(dict.fromkeys(record_ids or []))
    try:
        config = reusable_report_settings(values)
        start = parse_date(values.get("date_from", ""))
        end = parse_date(values.get("date_to", ""))
        if start and end and start > end:
            raise ValueError("The report start date must be on or before the end date.")
        eligible = {
            record.id: record
            for record in accomplishments.search(session, date_from=start, date_to=end)
            if record.report_inclusion
        }
        query = values.get("query", "").strip().casefold()
        eligible = {
            key: record
            for key, record in eligible.items()
            if not query
            or query
            in f"{record.title} {record.raw_note} {record.action} {' '.join(record.tags)}".casefold()
        }
        if not selected:
            raise ValueError("Select at least one accomplishment.")
        if any(key not in eligible for key in selected):
            raise ValueError(
                "Some selected accomplishments are no longer eligible for this scope. Review your selection."
            )
    except ValueError as exc:
        return report_page_response(request, session, values, selected, str(exc), 400)
    records = [eligible[key] for key in selected]
    template = session.get(ReportTemplate, template_id) if template_id else None
    try:
        report = generate_docx(
            session,
            config["title"],
            records,
            report_type=config.get("report_type", "custom"),
            template_id=template.id if template else "",
            template_content=config.get("content", template.content if template else ""),
            output_filename=config.get("output_filename", ""),
            layout=config.get("layout", "detailed"),
        )
    except OSError:
        session.rollback()
        return report_page_response(
            request,
            session,
            values,
            selected,
            "The report could not be written. Check free space and access to the CareerForge reports directory, then retry.",
            500,
        )
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
    ordered_items = [item_map[item_id] for item_id, _ in requested]
    session.add(
        AuditEvent(event_type="report.items_reordered", metadata_json={"report_id": report.id})
    )
    session.flush()
    regenerate_docx(session, report, ordered_items)
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
        filename=report.filters.get("output_filename") or Path(report.output_path).name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/exports")
def document_exports_page(
    request: Request,
    session: SessionDependency,
    _: User = Depends(current_user),
    scope: str = "current",
    project_id: str = "",
    include_archived: bool = False,
    include_unfinished: bool = False,
    q: str = "",
):
    try:
        records = document_exports.candidates(
            session, scope, project_id, include_archived, include_unfinished, q
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    preference = reporting_year.preferences(session)
    periods = {
        reporting_year.period_for(record.date_completed, preference)
        for record in accomplishments.search(session, include_archived=True)
        if record.date_completed and 1 < record.date_completed.year < 9999
    }
    return templates.TemplateResponse(
        "exports.html",
        context(
            request,
            records=records,
            scope=scope,
            project_id=project_id,
            include_archived=include_archived,
            include_unfinished=include_unfinished,
            query=q,
            periods=sorted(periods, key=lambda period: period.start, reverse=True),
            projects=list(session.scalars(select(Project).order_by(Project.name))),
        ),
    )


@app.post("/exports/download")
def download_accomplishments(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    format: Annotated[str, Form()],
    title: Annotated[str, Form()] = "Accomplishment Brag Sheet",
    record_ids: Annotated[list[str] | None, Form()] = None,
    scope: Annotated[str, Form()] = "current",
    project_id: Annotated[str, Form()] = "",
    include_archived: Annotated[bool, Form()] = False,
    include_unfinished: Annotated[bool, Form()] = False,
    include_notes: Annotated[bool, Form()] = False,
    reviewed: Annotated[bool, Form()] = False,
    q: Annotated[str, Form()] = "",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if format not in document_exports.MIME_TYPES:
        raise HTTPException(400, "Choose Word, ODT, or Excel.")
    if not reviewed:
        raise HTTPException(
            400, "Confirm you reviewed the selected records and sensitivity before downloading."
        )
    if not title.strip() or len(title) > 200:
        raise HTTPException(400, "Provide a document title of 1–200 characters.")
    selected = set(record_ids or [])
    if not selected:
        raise HTTPException(400, "Select at least one accomplishment.")
    try:
        allowed = document_exports.candidates(
            session, scope, project_id, include_archived, include_unfinished, q
        )
        if not selected.issubset({record.id for record in allowed}):
            raise ValueError(
                "Some selected records are no longer in this export scope. Refresh Exports and select again."
            )
        content = document_exports.generate(
            [record for record in allowed if record.id in selected],
            title.strip(),
            format,
            include_notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.add(
        AuditEvent(
            event_type="document.exported",
            metadata_json={
                "format": format,
                "record_ids": sorted(selected),
                "include_notes": include_notes,
            },
        )
    )
    session.commit()
    filename = (
        (re.sub(r"[^\w .'-]", "", title).strip(" .")[:100] or "accomplishments") + "." + format
    )
    return Response(
        content,
        media_type=document_exports.MIME_TYPES[format],
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "Cache-Control": "no-store",
        },
    )


@app.get("/git-sync")
def exports_page(request: Request, session: SessionDependency, _: User = Depends(current_user)):
    profiles = list(
        session.scalars(select(GitRepositoryProfile).order_by(GitRepositoryProfile.name))
    )
    return templates.TemplateResponse("git_sync.html", context(request, profiles=profiles))


def latest_export_files(session: Session, profile_id: str) -> list[str]:
    run = session.scalar(
        select(ExportRun)
        .where(ExportRun.profile_id == profile_id, ExportRun.status == "completed")
        .order_by(ExportRun.created_at.desc())
    )
    manifest = run.manifest if run and isinstance(run.manifest, dict) else {}
    files = manifest.get("files", [])
    return [str(filename) for filename in files if isinstance(filename, str)]


@app.post("/exports/profiles")
@app.post("/git-sync/profiles")
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
    return redirect("/git-sync")


@app.get("/exports/{profile_id}/preview")
@app.get("/git-sync/{profile_id}/preview")
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
            "git_sync.html",
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
        "git_sync.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            active_profile=profile,
            latest_export_files=latest_export_files(session, profile.id),
            manifest=manifest,
            repo_status=repo_status,
            repo_diff=repo_diff,
        ),
    )


@app.post("/exports/dry-run")
@app.post("/git-sync/dry-run")
def export_dry_run(
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    manifest = export_markdown(session, settings.data_dir / "temp" / "dry-run", dry_run=True)
    return templates.TemplateResponse(
        "git_sync.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            manifest=manifest,
        ),
    )


@app.post("/exports/{profile_id}/apply")
@app.post("/git-sync/{profile_id}/apply")
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
        session,
        Path(profile.repository_path) / profile.export_subdirectory,
        dry_run=False,
        profile_id=profile.id,
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
        "git_sync.html",
        context(
            request,
            profiles=list(session.scalars(select(GitRepositoryProfile))),
            active_profile=profile,
            latest_export_files=latest_export_files(session, profile.id),
            manifest=manifest,
            message="Markdown files were written. Review the Git preview before staging or committing.",
        ),
    )


@app.post("/exports/{profile_id}/commit")
@app.post("/git-sync/{profile_id}/commit")
def commit_export(
    profile_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    files: Annotated[list[str] | None, Form()] = None,
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "COMMIT":
        raise HTTPException(status_code=400, detail="Type COMMIT to create a local Git commit.")
    profile = session.get(GitRepositoryProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Git profile not found.")
    allowed = set(latest_export_files(session, profile.id))
    selected = files or []
    if not selected or not set(selected).issubset(allowed):
        raise HTTPException(
            status_code=400, detail="Select one or more files from the latest export."
        )
    repo_files = [str(Path(profile.export_subdirectory) / filename) for filename in selected]
    try:
        commit_id = git_ops.commit(
            Path(profile.repository_path),
            repo_files,
            f"Export CareerForge accomplishments ({len(repo_files)} files)",
            confirmed=True,
        )
    except git_ops.GitOperationError as exc:
        raise HTTPException(status_code=400, detail=f"Git commit failed: {exc}") from exc
    session.add(
        AuditEvent(
            event_type="git_export.committed",
            metadata_json={"profile_id": profile.id, "commit": commit_id, "count": len(repo_files)},
        )
    )
    session.commit()
    return redirect(f"/git-sync/{profile.id}/preview")


@app.post("/exports/{profile_id}/push")
@app.post("/git-sync/{profile_id}/push")
def push_export(
    profile_id: str,
    request: Request,
    session: SessionDependency,
    csrf: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    remote: Annotated[str, Form()] = "origin",
    _: User = Depends(current_user),
):
    require_csrf(request, csrf)
    if confirmation != "PUSH":
        raise HTTPException(
            status_code=400, detail="Type PUSH to send the clean branch to its remote."
        )
    profile = session.get(GitRepositoryProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Git profile not found.")
    if not remote.strip():
        raise HTTPException(status_code=400, detail="Provide a configured Git remote name.")
    try:
        git_ops.push(Path(profile.repository_path), remote.strip(), profile.branch, confirmed=True)
    except git_ops.GitOperationError as exc:
        raise HTTPException(status_code=400, detail=f"Git push failed: {exc}") from exc
    session.add(
        AuditEvent(
            event_type="git_export.pushed",
            metadata_json={
                "profile_id": profile.id,
                "remote": remote.strip(),
                "branch": profile.branch,
            },
        )
    )
    session.commit()
    return redirect(f"/git-sync/{profile.id}/preview")


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
