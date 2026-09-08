import hashlib
import html
import logging
import mimetypes
import os
import time
from pathlib import Path

import aiohttp
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = Path(os.getenv("KYC_UPLOAD_DIR", str(BASE_DIR / "kyc_uploads"))).resolve()
MAX_UPLOAD_BYTES = int(
    os.getenv(
        "KYC_MAX_UPLOAD_BYTES",
        os.getenv("KYC_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)),
    )
)

ADMIN_BOT_TOKEN = (
    os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0") or 0)


def _mask_phone(value: str | None) -> str:
    value = str(value or "")
    return f"{value[:4]}***{value[-4:]}" if len(value) >= 8 else "***"


def _mask_national_id(value: str | None) -> str:
    value = str(value or "")
    return f"***{value[-4:]}" if value else "***"


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


def _detect_upload_format(data: bytes) -> tuple[str, str] | None:
    """Return canonical MIME type and extension from the actual file signature."""

    # JPEG: FF D8 FF
    if len(data) >= 3 and data[:3].hex() == "ffd8ff":
        return "image/jpeg", ".jpg"

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if len(data) >= 8 and data[:8].hex() == "89504e470d0a1a0a":
        return "image/png", ".png"

    # WebP: RIFF....WEBP
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "image/webp", ".webp"

    # PDF
    if data.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"

    # HEIC / HEIF use an ISO Base Media File Format container.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]

        heic_brands = {
            b"heic",
            b"heix",
            b"hevc",
            b"hevx",
            b"heim",
            b"heis",
        }

        heif_brands = {
            b"mif1",
            b"msf1",
        }

        if brand in heic_brands:
            return "image/heic", ".heic"

        if brand in heif_brands:
            return "image/heif", ".heif"

    return None


async def _read_upload(
    upload: UploadFile,
    field_name: str,
) -> tuple[bytes, str, str]:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)

    if not data:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}_is_empty",
        )

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{field_name}_too_large",
        )

    detected = _detect_upload_format(data)

    if detected is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}_unsupported_file_type",
        )

    _mime_type, extension = detected
    digest = hashlib.sha256(data).hexdigest()

    return data, digest, extension


def _save_upload(user_id: int, level: int, label: str, data: bytes, extension: str) -> str:
    user_dir = UPLOAD_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = f"level{level}_{int(time.time() * 1000)}_{label}{extension}"
    target = (user_dir / filename).resolve()
    if UPLOAD_ROOT not in target.parents:
        raise HTTPException(status_code=400, detail="invalid_upload_path")
    target.write_bytes(data)
    try:
        target.chmod(0o600)
    except OSError:
        logger.warning("Could not chmod KYC upload %s", target.name)
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
                    logger.error("Telegram %s failed: %s %s", method, response.status, body[:300])
                    return False
                return True
    except Exception as exc:
        logger.warning("Telegram %s error: %s", method, type(exc).__name__)
        return False


async def _send_admin_text(text: str) -> bool:
    return await _telegram_request(
        "sendMessage",
        json_body={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"},
    )


async def _send_admin_file(path: str, caption: str) -> bool:
    if not ADMIN_BOT_TOKEN or not ADMIN_CHAT_ID:
        return False

    file_path = Path(path)
    extension = file_path.suffix.lower()

    # Telegram photo previews are convenient for common browser-safe images.
    # PDF, HEIC, HEIF and WebP are sent as documents instead.
    send_as_photo = extension in {".jpg", ".jpeg", ".png"}
    method = "sendPhoto" if send_as_photo else "sendDocument"
    field_name = "photo" if send_as_photo else "document"

    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as file_handle:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(ADMIN_CHAT_ID))
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
                form.add_field(
                    field_name,
                    file_handle,
                    filename=file_path.name,
                )

                async with session.post(
                    f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/{method}",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            "Telegram KYC %s failed: %s %s",
                            method,
                            response.status,
                            body[:300],
                        )
                        return False

                    return True

    except Exception as exc:
        logger.warning(
            "Telegram KYC file send failed: %s",
            type(exc).__name__,
        )
        return False


async def _notify_admin_submission(
    submission_id: int,
    user,
    level: int,
    paths: list[tuple[str, str]],
) -> None:
    text = (
        f"🪪 <b>KYC سطح {level} - درخواست جدید</b>\n"
        f"👤 {html.escape(str(user['first_name']))} {html.escape(str(user['last_name']))}\n"
        f"📱 {_mask_phone(user['phone_number'])}\n"
        f"🆔 {_mask_national_id(user['national_id'])}\n"
        f"🔢 Submission ID: {submission_id}\n\n"
        "برای تایید یا رد، از پنل ادمین استفاده کنید."
    )
    await _send_admin_text(text)
    for path, label in paths:
        await _send_admin_file(path, f"KYC سطح {level} | {label} | Submission #{submission_id}")


@router.get("/kyc/status")
async def get_kyc_status(user_id: int = Depends(get_current_user_id)):
    _ensure_schema()
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, verification_level FROM users WHERE id = ?",
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
    front_data, front_hash, front_ext = await _read_upload(front, "front")
    back_data, back_hash, back_ext = await _read_upload(back, "back")
    if front_hash == back_hash:
        raise HTTPException(status_code=400, detail="front_and_back_must_be_different_files")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        if int(user["verification_level"] or 1) < 1:
            raise HTTPException(status_code=403, detail="level1_required")
        existing = _latest_submission(conn, user_id, 2)
        if existing and existing["status"] == "pending":
            raise HTTPException(status_code=409, detail="level2_already_pending")

    front_path = _save_upload(user_id, 2, "front", front_data, front_ext)
    try:
        back_path = _save_upload(user_id, 2, "back", back_data, back_ext)
    except Exception:
        Path(front_path).unlink(missing_ok=True)
        raise

    try:
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO kyc_submissions
                   (user_id, level, status, front_path, back_path, front_sha256, back_sha256)
                   VALUES (?, 2, 'pending', ?, ?, ?, ?)""",
                (user_id, front_path, back_path, front_hash, back_hash),
            )
            submission_id = int(cursor.lastrowid)
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception:
        Path(front_path).unlink(missing_ok=True)
        Path(back_path).unlink(missing_ok=True)
        raise

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
    selfie_data, selfie_hash, selfie_ext = await _read_upload(selfie, "selfie")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        if int(user["verification_level"] or 1) < 2:
            raise HTTPException(status_code=403, detail="level2_required")
        existing = _latest_submission(conn, user_id, 3)
        if existing and existing["status"] == "pending":
            raise HTTPException(status_code=409, detail="level3_already_pending")

    selfie_path = _save_upload(user_id, 3, "selfie", selfie_data, selfie_ext)
    try:
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO kyc_submissions
                   (user_id, level, status, selfie_path, selfie_sha256)
                   VALUES (?, 3, 'pending', ?, ?)""",
                (user_id, selfie_path, selfie_hash),
            )
            submission_id = int(cursor.lastrowid)
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception:
        Path(selfie_path).unlink(missing_ok=True)
        raise

    await _notify_admin_submission(
        submission_id,
        user,
        3,
        [(selfie_path, "سلفی همراه کارت ملی در دست")],
    )
    return {"status": "pending", "submission_id": submission_id, "message": "level3_submitted"}
