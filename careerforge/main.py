import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, load_settings
from .database import Base, make_engine, make_session_factory
from .models import Accomplishment, AccomplishmentRevision, AuditEvent, User
from .schemas import AccomplishmentCreate, AccomplishmentResponse, AccomplishmentUpdate, LoginRequest, SetupRequest
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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "native-standalone"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_root / "index.html")

    @app.get("/api/setup-status")
    def setup_status(db: Annotated[Session, Depends(db_session)]):
        return {"setup_required": db.scalar(select(User.id).limit(1)) is None}

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
