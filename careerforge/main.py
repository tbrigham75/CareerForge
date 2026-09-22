import json
import sys
import time
from base64 import urlsafe_b64encode
from hashlib import sha256
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, load_settings
from .database import Base, make_engine, make_session_factory
from .models import AIProvider, Accomplishment, AccomplishmentRevision, AuditEvent, Goal, User
from .schemas import AIProviderCreate, AIProviderResponse, AccomplishmentCreate, AccomplishmentResponse, AccomplishmentUpdate, ChatRequest, DraftRequest, DraftResponse, GoalCreate, GoalResponse, LoginRequest, PasswordChange, SetupRequest
from .security import hash_password, issue_session, read_session, require_csrf, verify_password


def snapshot(item: Accomplishment) -> str:
    return json.dumps({field: (str(value) if value is not None else None) for field, value in {
        "title": item.title, "raw_note": item.raw_note, "action": item.action, "metric": item.metric,
        "impact": item.impact, "narrative": item.narrative, "date_started": item.date_started,
        "date_completed": item.date_completed, "status": item.status.value, "sensitivity": item.sensitivity.value,
        "github_export_eligible": item.github_export_eligible, "source_origin": item.source_origin,
    }.items()})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    static_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "careerforge" / "static"
    if not static_root.exists():
        static_root = Path(__file__).resolve().parent / "static"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(engine)
        yield

    app = FastAPI(title="CareerForge", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.client_seen = False
    app.state.last_client_heartbeat = 0.0
    cipher = Fernet(urlsafe_b64encode(sha256(settings.session_secret.encode()).digest()))
    app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])

    def db_session():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    def current_user(
        request: Request,
        db: Annotated[Session, Depends(db_session)],
        careerforge_session: Annotated[str | None, Cookie()] = None,
    ) -> tuple[User, dict]:
        if not careerforge_session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required.")
        session = read_session(settings.session_secret, careerforge_session)
        require_csrf(request, session)
        user = db.get(User, UUID(session["user_id"]))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required.")
        return user, session

    def audit(db: Session, action: str, target_type: str, target_id: str | None, actor_id: UUID | None = None):
        db.add(AuditEvent(actor_id=actor_id, action=action, target_type=target_type, target_id=target_id))

    def provider_response(provider: AIProvider) -> dict:
        return {"id": provider.id, "display_name": provider.display_name, "base_url": provider.base_url, "provider_class": provider.provider_class, "default_model": provider.default_model, "enabled": provider.enabled, "is_default": provider.is_default, "has_api_token": provider.encrypted_token is not None}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "native-standalone"}

    @app.post("/api/client-heartbeat", status_code=status.HTTP_204_NO_CONTENT)
    def client_heartbeat():
        app.state.client_seen = True
        app.state.last_client_heartbeat = time.monotonic()

    @app.get("/api/ai-providers", response_model=list[AIProviderResponse])
    def list_ai_providers(db: Annotated[Session, Depends(db_session)], _: Annotated[tuple[User, dict], Depends(current_user)]):
        return [provider_response(provider) for provider in db.scalars(select(AIProvider).where(AIProvider.enabled.is_(True)).order_by(AIProvider.display_name))]

    @app.post("/api/ai-providers", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED)
    def create_ai_provider(payload: AIProviderCreate, db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        if not payload.base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Provider URL must begin with http:// or https://.")
        if payload.is_default:
            for existing in db.scalars(select(AIProvider)):
                existing.is_default = False
        provider = AIProvider(**payload.model_dump(exclude={"api_token"}), encrypted_token=cipher.encrypt(payload.api_token.encode()).decode() if payload.api_token else None)
        db.add(provider); db.flush(); audit(db, "ai_provider.created", "ai_provider", str(provider.id), current[0].id); db.commit(); db.refresh(provider)
        return provider_response(provider)

    @app.post("/api/ai-providers/{provider_id}/test")
    def test_ai_provider(provider_id: UUID, db: Annotated[Session, Depends(db_session)], _: Annotated[tuple[User, dict], Depends(current_user)]):
        provider = db.get(AIProvider, provider_id)
        if not provider: raise HTTPException(status_code=404, detail="AI provider not found.")
        headers = {"Authorization": f"Bearer {cipher.decrypt(provider.encrypted_token.encode()).decode()}"} if provider.encrypted_token else {}
        try:
            response = httpx.get(provider.base_url.rstrip("/") + "/api/tags", headers=headers, timeout=10.0)
            response.raise_for_status()
            return {"ok": True, "models": [model.get("name") for model in response.json().get("models", [])]}
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Provider connection failed: {exc.__class__.__name__}") from exc

    @app.post("/api/ai-drafts", response_model=DraftResponse)
    def create_ai_draft(payload: DraftRequest, db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        provider = db.get(AIProvider, payload.provider_id) if payload.provider_id else db.scalar(select(AIProvider).where(AIProvider.is_default.is_(True), AIProvider.enabled.is_(True)))
        if not provider: raise HTTPException(status_code=409, detail="Configure and select an AI provider first.")
        prompt = "Use only the supplied factual note. Return JSON with title, action, metric, impact, supporting_narrative, placeholders_requiring_confirmation, follow_up_questions, confidence_notes. Never invent facts, metrics, outcomes, dates, systems, or claims. Missing facts must be visible placeholders. Note: " + payload.raw_note
        headers = {"Authorization": f"Bearer {cipher.decrypt(provider.encrypted_token.encode()).decode()}"} if provider.encrypted_token else {}
        try:
            response = httpx.post(provider.base_url.rstrip("/") + "/api/generate", headers=headers, json={"model": provider.default_model, "prompt": prompt, "format": "json", "stream": False}, timeout=60.0)
            response.raise_for_status(); draft = json.loads(response.json()["response"])
            audit(db, "ai_draft.generated", "ai_provider", str(provider.id), current[0].id); db.commit()
            return draft
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="AI draft failed; your original note was not changed.") from exc

    @app.post("/api/chat")
    def chat(payload: ChatRequest, db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        provider = db.get(AIProvider, payload.provider_id) if payload.provider_id else db.scalar(select(AIProvider).where(AIProvider.is_default.is_(True), AIProvider.enabled.is_(True)))
        if not provider: raise HTTPException(status_code=409, detail="Configure an AI provider in Settings before chatting.")
        headers = {"Authorization": f"Bearer {cipher.decrypt(provider.encrypted_token.encode()).decode()}"} if provider.encrypted_token else {}
        try:
            response = httpx.post(provider.base_url.rstrip("/") + "/api/generate", headers=headers, json={"model": provider.default_model, "prompt": payload.message, "stream": False}, timeout=60.0)
            response.raise_for_status(); reply = response.json()["response"]
            audit(db, "ai_chat.completed", "ai_provider", str(provider.id), current[0].id); db.commit()
            return {"reply": reply}
        except (httpx.HTTPError, KeyError) as exc:
            raise HTTPException(status_code=502, detail="AI chat failed; check the configured provider.") from exc

    @app.get("/api/goals", response_model=list[GoalResponse])
    def list_goals(db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        return list(db.scalars(select(Goal).where(Goal.user_id == current[0].id).order_by(Goal.created_at.desc())))

    @app.post("/api/goals", response_model=GoalResponse, status_code=201)
    def create_goal(payload: GoalCreate, db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        goal = Goal(user_id=current[0].id, **payload.model_dump()); db.add(goal); db.flush(); audit(db, "goal.created", "goal", str(goal.id), current[0].id); db.commit(); db.refresh(goal); return goal

    @app.post("/api/goals/suggestions")
    def suggest_goals(db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        provider = db.scalar(select(AIProvider).where(AIProvider.is_default.is_(True), AIProvider.enabled.is_(True)))
        if not provider: raise HTTPException(status_code=409, detail="Configure an AI provider in Settings before requesting suggestions.")
        accomplishments = list(db.scalars(select(Accomplishment).where(Accomplishment.deleted_at.is_(None)).order_by(Accomplishment.updated_at.desc()).limit(20)))
        if not accomplishments: raise HTTPException(status_code=409, detail="Save at least one accomplishment before requesting goal suggestions.")
        notes = "\n".join(f"- {item.raw_note or item.action or item.title}" for item in accomplishments)
        prompt = "Based only on these user accomplishments, propose three concise future professional goals. Do not invent facts or claim outcomes. Return JSON object {suggestions:[{title:string,details:string}]}. Accomplishments:\n" + notes
        headers = {"Authorization": f"Bearer {cipher.decrypt(provider.encrypted_token.encode()).decode()}"} if provider.encrypted_token else {}
        try:
            response = httpx.post(provider.base_url.rstrip("/") + "/api/generate", headers=headers, json={"model": provider.default_model, "prompt": prompt, "format": "json", "stream": False}, timeout=60.0)
            response.raise_for_status(); result = json.loads(response.json()["response"])
            audit(db, "goal_suggestions.generated", "ai_provider", str(provider.id), current[0].id); db.commit()
            return {"suggestions": result.get("suggestions", [])}
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="Goal suggestions failed; no goals were changed.") from exc

    @app.post("/api/password")
    def change_password(payload: PasswordChange, db: Annotated[Session, Depends(db_session)], current: Annotated[tuple[User, dict], Depends(current_user)]):
        user = current[0]
        if not verify_password(user.password_hash, payload.current_password): raise HTTPException(status_code=400, detail="Current password is incorrect.")
        user.password_hash = hash_password(payload.new_password); audit(db, "auth.password_changed", "user", str(user.id), user.id); db.commit()
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_root / "index.html")

    @app.get("/api/setup-status")
    def setup_status(db: Annotated[Session, Depends(db_session)]):
        return {"setup_required": db.scalar(select(User.id).limit(1)) is None}

    @app.get("/api/session")
    def session_status(
        db: Annotated[Session, Depends(db_session)],
        careerforge_session: Annotated[str | None, Cookie()] = None,
    ):
        if not careerforge_session:
            return {"authenticated": False}
        try:
            session = read_session(settings.session_secret, careerforge_session)
            user = db.get(User, UUID(session["user_id"]))
        except HTTPException:
            return {"authenticated": False}
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, "username": user.username, "csrf_token": session["csrf"]}

    @app.post("/api/setup", status_code=status.HTTP_201_CREATED)
    def setup(payload: SetupRequest, request: Request, response: Response, db: Annotated[Session, Depends(db_session)]):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initial setup is local-only.")
        if db.scalar(select(User.id).limit(1)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already completed.")
        user = User(username=payload.username, password_hash=hash_password(payload.password))
        db.add(user); db.flush(); audit(db, "setup.completed", "user", str(user.id), user.id); db.commit()
        token = issue_session(settings.session_secret, user.id)
        response.set_cookie("careerforge_session", token, httponly=True, secure=settings.secure_cookies, samesite="lax", max_age=60 * 60 * 12)
        return {"username": user.username, "csrf_token": read_session(settings.session_secret, token)["csrf"]}

    @app.post("/api/login")
    def login(payload: LoginRequest, response: Response, db: Annotated[Session, Depends(db_session)]):
        user = db.scalar(select(User).where(User.username == payload.username))
        if not user or not verify_password(user.password_hash, payload.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
        audit(db, "auth.login", "user", str(user.id), user.id); db.commit()
        token = issue_session(settings.session_secret, user.id)
        response.set_cookie("careerforge_session", token, httponly=True, secure=settings.secure_cookies, samesite="lax", max_age=60 * 60 * 12)
        return {"username": user.username, "csrf_token": read_session(settings.session_secret, token)["csrf"]}

    @app.post("/api/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(response: Response, current: Annotated[tuple[User, dict], Depends(current_user)]):
        response.delete_cookie("careerforge_session")

    @app.get("/api/accomplishments", response_model=list[AccomplishmentResponse])
    def list_accomplishments(
        db: Annotated[Session, Depends(db_session)],
        _: Annotated[tuple[User, dict], Depends(current_user)],
    ):
        return list(db.scalars(select(Accomplishment).where(Accomplishment.deleted_at.is_(None)).order_by(Accomplishment.updated_at.desc())))

    @app.post("/api/accomplishments", response_model=AccomplishmentResponse, status_code=status.HTTP_201_CREATED)
    def create_accomplishment(
        payload: AccomplishmentCreate,
        db: Annotated[Session, Depends(db_session)],
        current: Annotated[tuple[User, dict], Depends(current_user)],
    ):
        item = Accomplishment(**payload.model_dump())
        db.add(item); db.flush()
        db.add(AccomplishmentRevision(accomplishment_id=item.id, revision=1, snapshot_json=snapshot(item)))
        audit(db, "accomplishment.created", "accomplishment", str(item.id), current[0].id)
        db.commit(); db.refresh(item)
        return item

    @app.put("/api/accomplishments/{item_id}", response_model=AccomplishmentResponse)
    def update_accomplishment(
        item_id: UUID,
        payload: AccomplishmentUpdate,
        db: Annotated[Session, Depends(db_session)],
        current: Annotated[tuple[User, dict], Depends(current_user)],
    ):
        item = db.get(Accomplishment, item_id)
        if not item or item.deleted_at:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Accomplishment not found.")
        for key, value in payload.model_dump().items(): setattr(item, key, value)
        item.revision += 1
        db.flush(); db.add(AccomplishmentRevision(accomplishment_id=item.id, revision=item.revision, snapshot_json=snapshot(item), reason="updated"))
        audit(db, "accomplishment.updated", "accomplishment", str(item.id), current[0].id)
        db.commit(); db.refresh(item)
        return item

    @app.delete("/api/accomplishments/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_accomplishment(
        item_id: UUID,
        db: Annotated[Session, Depends(db_session)],
        current: Annotated[tuple[User, dict], Depends(current_user)],
    ):
        item = db.get(Accomplishment, item_id)
        if not item or item.deleted_at:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Accomplishment not found.")
        from .models import utc_now
        item.deleted_at = utc_now(); audit(db, "accomplishment.soft_deleted", "accomplishment", str(item.id), current[0].id); db.commit()

    app.mount("/assets", StaticFiles(directory=static_root), name="assets")
    return app


app = create_app()
