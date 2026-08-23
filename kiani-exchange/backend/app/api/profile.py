import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import dotenv_values

from ..auth import get_current_user_id, hash_password, verify_password
from ..database import get_db

router = APIRouter()

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROFILE_UPLOAD_DIR = Path(
    os.getenv("PROFILE_UPLOAD_DIR", str(BACKEND_DIR / "profile_uploads"))
).expanduser().resolve()
PROFILE_MAX_IMAGE_BYTES = int(os.getenv("PROFILE_MAX_IMAGE_BYTES", "5242880") or 5242880)
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailUpdateRequest(BaseModel):
    email: str = ""


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class TelegramLinkCompleteRequest(BaseModel):
    token: str
    telegram_chat_id: int
    telegram_username: str | None = None


def ensure_profile_schema() -> None:
    with get_db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        additions = {
            "email": "TEXT",
            "profile_picture_path": "TEXT",
            "telegram_chat_id": "INTEGER",
            "telegram_username": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_link_tokens_user ON telegram_link_tokens(user_id, used)"
        )


def _user_bot_token() -> str:
    explicit = os.getenv("TELEGRAM_USER_BOT_TOKEN", "").strip()
    if explicit:
        return explicit

    # main.py currently has a compatibility mapping for older admin helpers.
    # Read the normal/customer bot token directly from .env so profile linking
    # never accidentally uses the dedicated admin bot.
    values = dotenv_values(BACKEND_DIR / ".env")
    return str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()


async def _get_user_bot_username() -> str:
    configured = os.getenv("TELEGRAM_USER_BOT_USERNAME", "").strip().lstrip("@")
    if configured:
        return configured

    token = _user_bot_token()
    if not token:
        raise HTTPException(status_code=503, detail="telegram_user_bot_not_configured")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                data = await response.json()
                username = str(data.get("result", {}).get("username") or "").strip()
                if response.status == 200 and data.get("ok") and username:
                    return username
    except Exception as exc:
        raise HTTPException(status_code=503, detail="telegram_user_bot_unavailable") from exc

    raise HTTPException(status_code=503, detail="telegram_user_bot_unavailable")


def _profile_row(user_id: int):
    ensure_profile_schema()
    with get_db() as conn:
        return conn.execute(
            """SELECT id, first_name, last_name, phone_number, dob, kyc_status,
                      verification_level, email, profile_picture_path,
                      telegram_chat_id, telegram_username
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()


@router.get("/profile")
async def get_profile(user_id: int = Depends(get_current_user_id)):
    row = _profile_row(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    picture_path = str(row["profile_picture_path"] or "")
    return {
        "profile": {
            "id": row["id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "phone_number": row["phone_number"],
            "date_of_birth": row["dob"],
            "kyc_status": row["kyc_status"],
            "verification_level": int(row["verification_level"] or 1),
            "email": row["email"] or "",
            "has_profile_picture": bool(picture_path and Path(picture_path).is_file()),
            "telegram_connected": bool(row["telegram_chat_id"]),
            "telegram_username": row["telegram_username"] or "",
        }
    }


@router.put("/profile/email")
async def update_email(
    req: EmailUpdateRequest,
    user_id: int = Depends(get_current_user_id),
):
    ensure_profile_schema()
    email = req.email.strip().lower()
    if email and (len(email) > 254 or not EMAIL_RE.fullmatch(email)):
        raise HTTPException(status_code=400, detail="invalid_email")

    with get_db() as conn:
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (email or None, user_id))
    return {"status": "success", "email": email}


@router.post("/profile/change-password")
async def change_password(
    req: PasswordChangeRequest,
    user_id: int = Depends(get_current_user_id),
):
    if (
        len(req.new_password) < 8
        or not re.search(r"[A-Za-z]", req.new_password)
        or not re.search(r"\d", req.new_password)
    ):
        raise HTTPException(status_code=400, detail="weak_password")

    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="user_not_found")
        if not verify_password(req.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="current_password_incorrect")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(req.new_password), user_id),
        )

    return {"status": "success"}


@router.post("/profile/picture")
async def upload_profile_picture(
    picture: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    ensure_profile_schema()
    content_type = (picture.content_type or "").lower()
    suffix = ALLOWED_IMAGE_TYPES.get(content_type)
    if not suffix:
        raise HTTPException(status_code=400, detail="unsupported_image_type")

    data = await picture.read(PROFILE_MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="empty_image")
    if len(data) > PROFILE_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="image_too_large")

    PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(PROFILE_UPLOAD_DIR, 0o700)
    except OSError:
        pass

    filename = f"user-{user_id}-{secrets.token_hex(16)}{suffix}"
    destination = PROFILE_UPLOAD_DIR / filename
    destination.write_bytes(data)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass

    old_path = None
    with get_db() as conn:
        row = conn.execute("SELECT profile_picture_path FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            old_path = str(row["profile_picture_path"] or "")
        conn.execute(
            "UPDATE users SET profile_picture_path = ? WHERE id = ?",
            (str(destination), user_id),
        )

    if old_path:
        try:
            old = Path(old_path).resolve()
            if old != destination.resolve() and PROFILE_UPLOAD_DIR in old.parents:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    return {"status": "success"}


@router.get("/profile/picture")
async def get_profile_picture(user_id: int = Depends(get_current_user_id)):
    ensure_profile_schema()
    with get_db() as conn:
        row = conn.execute("SELECT profile_picture_path FROM users WHERE id = ?", (user_id,)).fetchone()
    path = Path(str(row["profile_picture_path"] or "")) if row else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="profile_picture_not_found")
    return FileResponse(path)


@router.post("/profile/telegram-link/start")
async def start_telegram_link(user_id: int = Depends(get_current_user_id)):
    ensure_profile_schema()
    username = await _get_user_bot_username()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    with get_db() as conn:
        conn.execute(
            "UPDATE telegram_link_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO telegram_link_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at.isoformat()),
        )

    return {
        "status": "success",
        "bot_username": username,
        "deep_link": f"https://t.me/{username}?start=connect_{token}",
        "expires_at": expires_at.isoformat(),
    }


@router.post("/profile/telegram-link/complete")
async def complete_telegram_link(req: TelegramLinkCompleteRequest):
    """Called by the existing customer Telegram bot after /start connect_<token>."""
    ensure_profile_schema()
    now = datetime.utcnow()
    with get_db() as conn:
        row = conn.execute(
            "SELECT token, user_id, expires_at, used FROM telegram_link_tokens WHERE token = ?",
            (req.token,),
        ).fetchone()
        if not row or int(row["used"] or 0):
            raise HTTPException(status_code=400, detail="invalid_or_used_link_token")
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_link_token") from exc
        if expires_at < now:
            raise HTTPException(status_code=400, detail="expired_link_token")

        conn.execute(
            """UPDATE users
               SET telegram_chat_id = ?, telegram_username = ?
               WHERE id = ?""",
            (req.telegram_chat_id, (req.telegram_username or "").lstrip("@") or None, row["user_id"]),
        )
        conn.execute("UPDATE telegram_link_tokens SET used = 1 WHERE token = ?", (req.token,))

    return {"status": "success"}


@router.delete("/profile/telegram-link")
async def disconnect_telegram(user_id: int = Depends(get_current_user_id)):
    ensure_profile_schema()
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET telegram_chat_id = NULL, telegram_username = NULL WHERE id = ?",
            (user_id,),
        )
        conn.execute(
            "UPDATE telegram_link_tokens SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
    return {"status": "success"}
