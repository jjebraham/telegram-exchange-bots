import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .auth import ALGORITHM, JWT_ISSUER, get_jwt_secret

ADMIN_AUDIENCE = "kiani-admin"
admin_security = HTTPBearer()


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    role: str


def get_admin_token_expire_minutes() -> int:
    raw = os.getenv("ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES", "30").strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise RuntimeError("ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES must be an integer") from exc
    if not 5 <= minutes <= 480:
        raise RuntimeError("ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 480")
    return minutes


def _configured_admin_accounts() -> tuple[tuple[str, str, str], ...]:
    return (
        (
            "admin",
            os.getenv("ADMIN_PANEL_USERNAME", "").strip(),
            os.getenv("ADMIN_PANEL_PASSWORD", ""),
        ),
        (
            "support",
            os.getenv("SUPPORT_PANEL_USERNAME", "").strip(),
            os.getenv("SUPPORT_PANEL_PASSWORD", ""),
        ),
        (
            "viewer",
            os.getenv("VIEWER_PANEL_USERNAME", "").strip(),
            os.getenv("VIEWER_PANEL_PASSWORD", ""),
        ),
    )


def validate_admin_config() -> None:
    get_admin_token_expire_minutes()
    accounts = _configured_admin_accounts()
    admin = accounts[0]
    if not admin[1] or not admin[2]:
        raise RuntimeError("ADMIN_PANEL_USERNAME and ADMIN_PANEL_PASSWORD must be configured")


def verify_admin_credentials(username: str, password: str) -> AdminIdentity | None:
    username = (username or "").strip()
    password = password or ""
    for role, configured_user, configured_password in _configured_admin_accounts():
        if not configured_user or not configured_password:
            continue
        user_ok = secrets.compare_digest(username, configured_user)
        password_ok = secrets.compare_digest(password, configured_password)
        if user_ok and password_ok:
            return AdminIdentity(username=configured_user, role=role)
    return None


def create_admin_access_token(identity: AdminIdentity) -> tuple[str, int]:
    minutes = get_admin_token_expire_minutes()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=minutes)
    payload = {
        "sub": identity.username,
        "role": identity.role,
        "token_type": "admin",
        "iss": JWT_ISSUER,
        "aud": ADMIN_AUDIENCE,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)
    return token, minutes * 60


def decode_admin_token(token: str) -> AdminIdentity:
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[ALGORITHM],
            audience=ADMIN_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        if payload.get("token_type") != "admin":
            raise JWTError("wrong token type")
        username = str(payload.get("sub") or "").strip()
        role = str(payload.get("role") or "").strip()
        if not username or role not in {"admin", "support", "viewer"}:
            raise JWTError("invalid admin claims")
        return AdminIdentity(username=username, role=role)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_expired_admin_token",
        )


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(admin_security),
) -> AdminIdentity:
    return decode_admin_token(credentials.credentials)


def require_admin_roles(*allowed_roles: str) -> Callable:
    allowed = set(allowed_roles)

    def dependency(identity: AdminIdentity = Depends(get_current_admin)) -> AdminIdentity:
        if identity.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_admin_role")
        return identity

    return dependency
