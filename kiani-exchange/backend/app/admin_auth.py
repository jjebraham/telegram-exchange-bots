from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

ALGORITHM = "HS256"
DEFAULT_TTL_HOURS = 12
DEFAULT_SECRET_FILE = (
    Path(__file__).resolve().parent.parent / ".admin_session_secret"
)

_optional_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    env_secret = os.environ.get("KIANI_ADMIN_SESSION_SECRET", "").strip()
    if env_secret:
        return env_secret

    secret_path = Path(
        os.environ.get(
            "KIANI_ADMIN_SESSION_SECRET_FILE",
            str(DEFAULT_SECRET_FILE),
        )
    ).expanduser()
    try:
        value = secret_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Admin session secret is unavailable: {secret_path}"
        ) from exc
    if len(value) < 32:
        raise RuntimeError("Admin session secret must contain at least 32 characters")
    return value


def _ttl_hours() -> int:
    raw = os.environ.get("KIANI_ADMIN_SESSION_HOURS", str(DEFAULT_TTL_HOURS))
    try:
        hours = int(raw)
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return min(max(hours, 1), 72)


def create_admin_session_token(username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "username": username,
        "role": role,
        "token_type": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_ttl_hours())).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_admin_session_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except (JWTError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_expired_admin_session",
        ) from exc

    username = str(payload.get("username") or payload.get("sub") or "").strip()
    role = str(payload.get("role") or "").strip()
    if payload.get("token_type") != "admin" or not username or role not in {
        "admin",
        "support",
        "viewer",
    }:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_admin_session",
        )
    return {"username": username, "role": role}


def optional_admin_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> dict[str, str] | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_admin_auth_scheme",
        )
    return decode_admin_session_token(credentials.credentials)
