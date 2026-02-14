import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from ..database import get_db
from ..auth import hash_password, verify_password

router = APIRouter(prefix="/admin", tags=["admin-security"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "7"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_jwt(payload: dict, ttl: timedelta) -> str:
    data = payload.copy()
    data["exp"] = utc_now() + ttl
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def _decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    return authorization.split(" ", 1)[1].strip()


def _ensure_schema() -> None:
    with get_db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS admin_security_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            role TEXT DEFAULT 'Moderator',
            two_factor_enabled INTEGER DEFAULT 0,
            totp_secret TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            is_revoked INTEGER DEFAULT 0,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS password_reset_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            key_prefix TEXT NOT NULL,
            key_hash TEXT UNIQUE NOT NULL,
            created_by INTEGER,
            is_active INTEGER DEFAULT 1,
            usage_count INTEGER DEFAULT 0,
            last_used_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS external_api_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT UNIQUE NOT NULL,
            base_url TEXT NOT NULL,
            api_key_encrypted TEXT,
            proxy_url TEXT,
            is_active INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )


class LoginRequest(BaseModel):
    phone: str
    password: str
    totp_code: str | None = None


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetStartRequest(BaseModel):
    phone: str


class PasswordResetCompleteRequest(BaseModel):
    phone: str
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)


class ApiKeyCreateRequest(BaseModel):
    name: str


class ExternalApiConfigRequest(BaseModel):
    provider: str
    base_url: str
    api_key: str | None = None
    proxy_url: str | None = None
    is_active: bool = True


def _get_current_admin(authorization: str | None = Header(default=None)) -> dict:
    token = _extract_bearer(authorization)
    payload = _decode_jwt(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="invalid_access_token")

    user_id = payload.get("user_id")
    with get_db() as conn:
        row = conn.execute(
            """SELECT u.id, u.phone_number, s.role FROM users u
            LEFT JOIN admin_security_settings s ON s.user_id = u.id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="admin_not_found")
    return {"id": row["id"], "phone": row["phone_number"], "role": row["role"] or "Moderator"}


def _require_roles(admin: dict, allowed: set[str]):
    if admin["role"] not in allowed:
        raise HTTPException(status_code=403, detail="insufficient_role")


@router.on_event("startup")
def setup_tables():
    _ensure_schema()


@router.post("/auth/login")
def admin_login(payload: LoginRequest, request: Request):
    _ensure_schema()
    ip = request.client.host if request.client else "0.0.0.0"
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, phone_number, password_hash FROM users WHERE phone_number = ?",
            (payload.phone,),
        ).fetchone()
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="invalid_credentials")

        setting = conn.execute(
            "SELECT role, two_factor_enabled, totp_secret FROM admin_security_settings WHERE user_id = ?",
            (user["id"],),
        ).fetchone()

        if setting and setting["two_factor_enabled"]:
            if not payload.totp_code or not pyotp.TOTP(setting["totp_secret"]).verify(payload.totp_code, valid_window=1):
                raise HTTPException(status_code=401, detail="invalid_totp")

        access_token = _create_jwt(
            {"type": "access", "user_id": user["id"], "role": (setting["role"] if setting else "Moderator")},
            timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
        )
        raw_refresh = secrets.token_urlsafe(48)
        refresh_hash = _hash_token(raw_refresh)
        exp = utc_now() + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], refresh_hash, exp.isoformat()),
        )

    return {"access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer", "ip": ip}


@router.post("/auth/refresh")
def refresh_tokens(payload: TokenRefreshRequest):
    refresh_hash = _hash_token(payload.refresh_token)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, is_revoked, expires_at FROM refresh_tokens WHERE token_hash = ?",
            (refresh_hash,),
        ).fetchone()
        if not row or row["is_revoked"]:
            raise HTTPException(status_code=401, detail="refresh_token_revoked")
        if datetime.fromisoformat(row["expires_at"]) < utc_now():
            raise HTTPException(status_code=401, detail="refresh_token_expired")

        conn.execute("UPDATE refresh_tokens SET is_revoked = 1 WHERE id = ?", (row["id"],))
        new_refresh = secrets.token_urlsafe(48)
        new_refresh_hash = _hash_token(new_refresh)
        new_exp = utc_now() + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (row["user_id"], new_refresh_hash, new_exp.isoformat()),
        )

    access_token = _create_jwt({"type": "access", "user_id": row["user_id"]}, timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES))
    return {"access_token": access_token, "refresh_token": new_refresh}


@router.post("/auth/logout")
def logout(payload: TokenRefreshRequest):
    with get_db() as conn:
        conn.execute("UPDATE refresh_tokens SET is_revoked = 1 WHERE token_hash = ?", (_hash_token(payload.refresh_token),))
    return {"status": "revoked"}


@router.post("/auth/2fa/enable")
def enable_2fa(admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    secret = pyotp.random_base32()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO admin_security_settings (user_id, role, two_factor_enabled, totp_secret)
            VALUES (?, COALESCE((SELECT role FROM admin_security_settings WHERE user_id = ?), 'Admin'), 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET two_factor_enabled = 1, totp_secret = excluded.totp_secret""",
            (admin["id"], admin["id"], secret),
        )
    return {"secret": secret, "otpauth": pyotp.totp.TOTP(secret).provisioning_uri(name=admin["phone"], issuer_name="KianiExchange")}


@router.post("/auth/password-reset/start")
def start_password_reset(payload: PasswordResetStartRequest):
    code = f"{secrets.randbelow(999999):06d}"
    code_hash = _hash_token(code)
    expires_at = utc_now() + timedelta(minutes=10)
    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE phone_number = ?", (payload.phone,)).fetchone()
        if user:
            conn.execute(
                "INSERT INTO password_reset_otps (user_id, phone, code_hash, expires_at) VALUES (?, ?, ?, ?)",
                (user["id"], payload.phone, code_hash, expires_at.isoformat()),
            )
    return {"status": "otp_generated", "otp_for_dev": code}


@router.post("/auth/password-reset/complete")
def complete_password_reset(payload: PasswordResetCompleteRequest):
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, user_id, expires_at, is_used FROM password_reset_otps
            WHERE phone = ? AND code_hash = ? ORDER BY id DESC LIMIT 1""",
            (payload.phone, _hash_token(payload.otp)),
        ).fetchone()
        if not row or row["is_used"]:
            raise HTTPException(status_code=400, detail="invalid_otp")
        if datetime.fromisoformat(row["expires_at"]) < utc_now():
            raise HTTPException(status_code=400, detail="expired_otp")

        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(payload.new_password), row["user_id"]))
        conn.execute("UPDATE password_reset_otps SET is_used = 1 WHERE id = ?", (row["id"],))
    return {"status": "password_updated"}


@router.post("/auth/api-keys")
def create_api_key(payload: ApiKeyCreateRequest, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    raw = f"kea_{secrets.token_urlsafe(32)}"
    key_hash = _hash_token(raw)
    prefix = raw[:12]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO api_keys (name, key_prefix, key_hash, created_by) VALUES (?, ?, ?, ?)",
            (payload.name, prefix, key_hash, admin["id"]),
        )
    return {"api_key": raw, "name": payload.name, "prefix": prefix}


@router.get("/auth/api-keys")
def list_api_keys(admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin", "Moderator"})
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, key_prefix, is_active, usage_count, created_at FROM api_keys").fetchall()
    return [dict(row) for row in rows]


@router.delete("/auth/api-keys/{key_id}")
def revoke_api_key(key_id: int, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    with get_db() as conn:
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    return {"status": "revoked", "id": key_id}


@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    with get_db() as conn:
        conn.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
    return {"status": "banned", "user_id": user_id}


class FeeUpdateRequest(BaseModel):
    toman_to_tl_factor: float


@router.patch("/fees")
def edit_fees(payload: FeeUpdateRequest, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    with get_db() as conn:
        conn.execute("UPDATE rate_settings SET toman_to_tl_factor = ? WHERE id = 1", (payload.toman_to_tl_factor,))
    return {"status": "updated"}


@router.get("/api-management")
def list_external_apis(admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    with get_db() as conn:
        rows = conn.execute("SELECT id, provider, base_url, proxy_url, is_active, updated_at FROM external_api_configs").fetchall()
    return [dict(r) for r in rows]


@router.post("/api-management")
def upsert_external_api(payload: ExternalApiConfigRequest, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    api_key_encrypted = base64.b64encode((payload.api_key or "").encode()).decode() if payload.api_key else None
    with get_db() as conn:
        conn.execute(
            """INSERT INTO external_api_configs (provider, base_url, api_key_encrypted, proxy_url, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                base_url = excluded.base_url,
                api_key_encrypted = COALESCE(excluded.api_key_encrypted, external_api_configs.api_key_encrypted),
                proxy_url = excluded.proxy_url,
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (payload.provider.lower(), payload.base_url, api_key_encrypted, payload.proxy_url, 1 if payload.is_active else 0),
        )
    return {"status": "saved", "provider": payload.provider.lower()}


@router.delete("/api-management/{provider}")
def remove_external_api(provider: str, admin=Depends(_get_current_admin)):
    _require_roles(admin, {"SuperAdmin", "Admin"})
    with get_db() as conn:
        conn.execute("DELETE FROM external_api_configs WHERE provider = ?", (provider.lower(),))
    return {"status": "deleted", "provider": provider.lower()}
