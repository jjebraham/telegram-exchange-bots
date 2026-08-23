import hashlib
import json
import logging
import mimetypes
import os
import time
from pathlib import Path

import aiohttp
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import get_current_user_id
from ..database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = Path(os.getenv("KYC_UPLOAD_DIR", str(BASE_DIR / "kyc_uploads"))).resolve()
MAX_IMAGE_BYTES = int(os.getenv("KYC_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

ADMIN_BOT_TOKEN = (
    os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0") or 0)


class AdminKycDecision(BaseModel):
    username: str
    password: str
    reason: str | None = None


def _admin_role(username: str, password: str) -> str | None:
    pairs = (
        ("admin", os.getenv("ADMIN_PANEL_USERNAME", ""), os.getenv("ADMIN_PANEL_PASSWORD", "")),
        ("support", os.getenv("SUPPORT_PANEL_USERNAME", ""), os.getenv("SUPPORT_PANEL_PASSWORD", "")),
        ("viewer", os.getenv("VIEWER_PANEL_USERNAME", ""), os.getenv("VIEWER_PANEL_PASSWORD", "")),
    )
    for role, configured_user, configured_password in pairs:
        if configured_user and configured_password and username == configured_user and password == configured_password:
            return role
    return None


def _require_admin(username: str, password: str, allow_support: bool = False) -> str:
    role = _admin_role(username, password)
    allowed = {"admin", "support"} if allow_support else {"admin"}
    if role not in allowed:
        raise HTTPException(status_code=401, detail="unauthorized")
    return role


def _ensure_schema() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kyc_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                front_path TEXT,
                back_path TEXT,
                selfie_path TEXT,
                front_sha256 TEXT,
                back_sha256 TEXT,
                selfie_sha256 TEXT,
                rejection_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_by TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kyc_submissions_user_level ON kyc_submissions(user_id, level, id DESC)"
        )


def _submission_dict(row) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "level": row["level"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "has_front": bool(row["front_path"]),
        "has_back": bool(row["back_path"]),
        "has_selfie": bool(row["selfie_path"]),
    }


def _latest_submission(conn, user_id: int, level: int):
    return conn.execute(
        "SELECT * FROM kyc_submissions WHERE user_id = ? AND level = ? ORDER BY id DESC LIMIT 1",
        (user_id, level),
    ).fetchone()


async def _read_image(upload: UploadFile, field_name: str) -> tuple[bytes, str, str]:
    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"{field_name}_must_be_jpeg_png_or_webp")

    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail=f"{field_name}_is_empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"{field_name}_too_large")

    digest = hashlib.sha256(data).hexdigest()
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    if extension == ".jpe":
        extension = ".jpg"
    return data, digest, extension


def _save_image(user_id: int, level: int, label: str, data: bytes, extension: str) -> str:
    user_dir = UPLOAD_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"level{level}_{int(time.time() * 1000)}_{label}{extension}"
    target = (user_dir / filename).resolve()
    if UPLOAD_ROOT not in target.parents:
        raise HTTPException(status_code=400, detail="invalid_upload_path")
    target.write_bytes(data)
    return str(target)


async def _telegram_request(method: str, *, data=None, json_body=None) -> bool:
    if not ADMIN_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.warning("KYC admin Telegram notification skipped: admin bot token/chat ID not configured")
        return False
    url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=data,
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error("Telegram %s failed: %s %s", method, response.status, body[:500])
                    return False
                return True
    except Exception as exc:
        logger.exception("Telegram %s error: %s", method, exc)
        return False


async def _send_admin_text(text: str) -> bool:
    return await _telegram_request(
        "sendMessage",
        json_body={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"},
    )


async def _send_admin_photo(path: str, caption: str) -> bool:
    if not ADMIN_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.warning("KYC admin photo skipped: admin bot token/chat ID not configured")
        return False
    url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendPhoto"
    try:
        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as fh:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(ADMIN_CHAT_ID))
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
                form.add_field("photo", fh, filename=Path(path).name)
                async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error("Telegram sendPhoto failed: %s %s", response.status, body[:500])
                        return False
                    return True
    except Exception as exc:
        logger.exception("Telegram sendPhoto error: %s", exc)
        return False


async def _notify_admin_submission(submission_id: int, user, level: int, paths: list[tuple[str, str]]) -> None:
    text = (
        f"🪪 <b>KYC سطح {level} - درخواست جدید</b>\n"
        f"👤 {user['first_name']} {user['last_name']}\n"
        f"📱 {user['phone_number']}\n"
        f"🆔 {user['national_id']}\n"
        f"🔢 Submission ID: {submission_id}\n\n"
        "برای تایید یا رد، از بخش KYC پنل ادمین استفاده کنید."
    )
    await _send_admin_text(text)
    for path, label in paths:
        await _send_admin_photo(path, f"KYC سطح {level} | {label} | Submission #{submission_id}")


async def _notify_admin_decision(submission_id: int, level: int, status: str, reason: str | None) -> None:
    emoji = "✅" if status == "approved" else "❌"
    suffix = f"\nدلیل: {reason}" if reason else ""
    await _send_admin_text(f"{emoji} KYC سطح {level} | Submission #{submission_id} => {status}{suffix}")


@router.get("/kyc/status")
async def get_kyc_status(user_id: int = Depends(get_current_user_id)):
    _ensure_schema()
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, first_name, last_name, phone_number, national_id, verification_level FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        level2 = _latest_submission(conn, user_id, 2)
        level3 = _latest_submission(conn, user_id, 3)

    return {
        "verification_level": int(user["verification_level"] or 1),
        "level1": {"status": "approved"},
        "level2": _submission_dict(level2),
        "level3": _submission_dict(level3),
    }


@router.post("/kyc/level2")
async def submit_level2(
    front: UploadFile = File(...),
    back: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    _ensure_schema()
    front_data, front_hash, front_ext = await _read_image(front, "front")
    back_data, back_hash, back_ext = await _read_image(back, "back")

    if front_hash == back_hash:
        raise HTTPException(status_code=400, detail="front_and_back_must_be_different_files")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        level = int(user["verification_level"] or 1)
        if level < 1:
            raise HTTPException(status_code=403, detail="level1_required")
        existing = _latest_submission(conn, user_id, 2)
        if existing and existing["status"] == "pending":
            raise HTTPException(status_code=409, detail="level2_already_pending")

    front_path = _save_image(user_id, 2, "front", front_data, front_ext)
    back_path = _save_image(user_id, 2, "back", back_data, back_ext)

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO kyc_submissions
               (user_id, level, status, front_path, back_path, front_sha256, back_sha256)
               VALUES (?, 2, 'pending', ?, ?, ?, ?)""",
            (user_id, front_path, back_path, front_hash, back_hash),
        )
        submission_id = cursor.lastrowid
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    await _notify_admin_submission(
        submission_id,
        user,
        2,
        [(front_path, "روی کارت ملی"), (back_path, "پشت کارت ملی")],
    )
    return {"status": "pending", "submission_id": submission_id, "message": "level2_submitted"}


@router.post("/kyc/level3")
async def submit_level3(
    selfie: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    _ensure_schema()
    selfie_data, selfie_hash, selfie_ext = await _read_image(selfie, "selfie")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        level = int(user["verification_level"] or 1)
        if level < 2:
            raise HTTPException(status_code=403, detail="level2_required")
        existing = _latest_submission(conn, user_id, 3)
        if existing and existing["status"] == "pending":
            raise HTTPException(status_code=409, detail="level3_already_pending")

    selfie_path = _save_image(user_id, 3, "selfie", selfie_data, selfie_ext)
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO kyc_submissions
               (user_id, level, status, selfie_path, selfie_sha256)
               VALUES (?, 3, 'pending', ?, ?)""",
            (user_id, selfie_path, selfie_hash),
        )
        submission_id = cursor.lastrowid
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    await _notify_admin_submission(
        submission_id,
        user,
        3,
        [(selfie_path, "سلفی همراه کارت ملی در دست")],
    )
    return {"status": "pending", "submission_id": submission_id, "message": "level3_submitted"}


@router.get("/admin/kyc/submissions")
async def admin_list_kyc_submissions(username: str, password: str, status: str | None = None):
    _require_admin(username, password, allow_support=True)
    _ensure_schema()
    query = """
        SELECT k.*, u.first_name, u.last_name, u.phone_number, u.national_id, u.verification_level
        FROM kyc_submissions k
        JOIN users u ON u.id = k.user_id
    """
    params: tuple = ()
    if status:
        query += " WHERE k.status = ?"
        params = (status,)
    query += " ORDER BY k.id DESC LIMIT 300"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return {
        "submissions": [
            {
                **_submission_dict(row),
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "phone_number": row["phone_number"],
                "national_id": row["national_id"],
                "verification_level": row["verification_level"],
            }
            for row in rows
        ]
    }


@router.get("/admin/kyc/submissions/{submission_id}/file/{kind}")
async def admin_kyc_file_metadata(submission_id: int, kind: str, username: str, password: str):
    """Return the server-side file path for controlled admin diagnostics.

    The file itself is deliberately not exposed as a public static URL. Admins receive
    the images through Telegram and can review state here without making KYC documents public.
    """
    _require_admin(username, password, allow_support=True)
    if kind not in {"front", "back", "selfie"}:
        raise HTTPException(status_code=400, detail="invalid_file_kind")
    _ensure_schema()
    column = {"front": "front_path", "back": "back_path", "selfie": "selfie_path"}[kind]
    with get_db() as conn:
        row = conn.execute(
            f"SELECT {column} AS path FROM kyc_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
    if not row or not row["path"]:
        raise HTTPException(status_code=404, detail="file_not_found")
    return {"exists": Path(row["path"]).is_file(), "filename": Path(row["path"]).name}



@router.post("/admin/kyc/submissions/{submission_id}/file/{kind}")
async def admin_kyc_file(
    submission_id: int,
    kind: str,
    req: AdminKycDecision,
):
    """Securely return a KYC image to an authenticated admin/support user."""
    _require_admin(req.username, req.password, allow_support=True)

    if kind not in {"front", "back", "selfie"}:
        raise HTTPException(status_code=400, detail="invalid_file_kind")

    _ensure_schema()

    column = {
        "front": "front_path",
        "back": "back_path",
        "selfie": "selfie_path",
    }[kind]

    with get_db() as conn:
        row = conn.execute(
            f"SELECT {column} AS path FROM kyc_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()

    if not row or not row["path"]:
        raise HTTPException(status_code=404, detail="file_not_found")

    file_path = Path(row["path"]).resolve()

    # Never allow this endpoint to read files outside the private KYC directory.
    if UPLOAD_ROOT not in file_path.parents:
        raise HTTPException(status_code=403, detail="invalid_file_path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="file_not_found")

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.post("/admin/kyc/submissions/{submission_id}/approve")
async def admin_approve_kyc(submission_id: int, req: AdminKycDecision):
    reviewer = _require_admin(req.username, req.password)
    _ensure_schema()
    with get_db() as conn:
        submission = conn.execute("SELECT * FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="submission_not_found")
        if submission["status"] != "pending":
            raise HTTPException(status_code=409, detail="submission_already_reviewed")
        level = int(submission["level"])
        if level not in {2, 3}:
            raise HTTPException(status_code=400, detail="invalid_kyc_level")
        conn.execute(
            "UPDATE kyc_submissions SET status='approved', rejection_reason=NULL, reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reviewer, submission_id),
        )
        conn.execute(
            "UPDATE users SET verification_level = CASE WHEN verification_level < ? THEN ? ELSE verification_level END, kyc_status='Approved' WHERE id=?",
            (level, level, submission["user_id"]),
        )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("kyc_approved", json.dumps({"submission_id": submission_id, "level": level, "user_id": submission["user_id"]})),
        )
    await _notify_admin_decision(submission_id, level, "approved", None)
    return {"status": "approved", "verification_level": level}


@router.post("/admin/kyc/submissions/{submission_id}/reject")
async def admin_reject_kyc(submission_id: int, req: AdminKycDecision):
    reviewer = _require_admin(req.username, req.password)
    reason = (req.reason or "مدارک قابل تایید نیست؛ لطفاً دوباره بارگذاری کنید.").strip()
    _ensure_schema()
    with get_db() as conn:
        submission = conn.execute("SELECT * FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="submission_not_found")
        if submission["status"] != "pending":
            raise HTTPException(status_code=409, detail="submission_already_reviewed")
        level = int(submission["level"])
        conn.execute(
            "UPDATE kyc_submissions SET status='rejected', rejection_reason=?, reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reason, reviewer, submission_id),
        )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("kyc_rejected", json.dumps({"submission_id": submission_id, "level": level, "user_id": submission["user_id"], "reason": reason}, ensure_ascii=False)),
        )
    await _notify_admin_decision(submission_id, level, "rejected", reason)
    return {"status": "rejected", "reason": reason}
