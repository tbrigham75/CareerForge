from __future__ import annotations

import secrets
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer


PASSWORD_HASHER = PasswordHasher()
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def issue_session(secret: str, user_id: UUID) -> str:
    return URLSafeTimedSerializer(secret, salt="careerforge-session").dumps({"user_id": str(user_id), "csrf": secrets.token_urlsafe(24)})


def read_session(secret: str, value: str) -> dict:
    try:
        return URLSafeTimedSerializer(secret, salt="careerforge-session").loads(value, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.") from exc


def require_csrf(request: Request, session: dict) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token")
        if not supplied or not secrets.compare_digest(supplied, session["csrf"]):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
