import html
import json
import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..admin_auth import (
    AdminIdentity,
    create_admin_access_token,
    get_current_admin,
    require_admin_roles,
    verify_admin_credentials,
)
from ..admin_notify import now_text, send_admin_message
from ..auth import hash_password
from ..database import get_db
from ..user_notification import send_user_message
from . import kyc as kyc_api
from . import rates as rates_api

logger = logging.getLogger(__name__)
router = APIRouter()


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class AdminMessageRequest(BaseModel):
    message: str
    user_id: int | None = None


class FaqRequest(BaseModel):
    question: str
    answer: str


class StatusUpdateRequest(BaseModel):
    status: str
    receipt_photo_url: str | None = None
    receipt_description: str | None = None
    payment_link: str | None = None


class KycDecisionRequest(BaseModel):
    reason: str | None = None


class AdminRateSettings(BaseModel):
    toman_to_tl_manual_rate: float = 0.0
    toman_to_tl_percentage: float = -0.5
    tl_to_toman_manual_rate: float = 0.0
    tl_to_toman_percentage: float = -6.0
    tl_to_usdt_manual_rate: float = 0.0
    tl_to_usdt_percentage: float = 2.0
    usdt_to_tl_manual_rate: float = 0.0
    usdt_to_tl_percentage: float = -2.0
    toman_to_usdt_manual_rate: float = 0.0
    toman_to_usdt_percentage: float = 1.0
    usdt_to_toman_manual_rate: float = 0.0
    usdt_to_toman_percentage: float = -1.0


READ_ROLES = require_admin_roles("admin", "support", "viewer")
WRITE_ROLES = require_admin_roles("admin", "support")
ADMIN_ONLY = require_admin_roles("admin")

VALID_TRANSACTION_STATUSES = {
    "Pending",
    "Under Review",
    "Waiting for User's Payment",
    "Waiting for Admin to Pay",
    "Under Process",
    "Done",
    "Rejected",
    "Canceled by Admin",
    "Canceled by User",
    "Expired",
}


def _write_admin_log(action: str, details: dict | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            (action, json.dumps(details or {}, ensure_ascii=False)),
        )


def _mask_phone(value: str | None) -> str:
    value = str(value or "")
    return f"{value[:4]}***{value[-4:]}" if len(value) >= 8 else "***"


def _mask_national_id(value: str | None) -> str:
    value = str(value or "")
    return f"***{value[-4:]}" if value else "***"


def _mask_card(value: str | None) -> str:
    value = str(value or "")
    return f"**** **** **** {value[-4:]}" if value else "****"


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (name,),
        ).fetchone()
    )


def _ensure_kyc_schema() -> None:
    kyc_api._ensure_schema()


def _submission_dict(row) -> dict:
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
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone_number": _mask_phone(row["phone_number"]),
        "national_id": _mask_national_id(row["national_id"]),
        "verification_level": int(row["verification_level"] or 1),
    }


def _validate_new_password(password: str) -> None:
    if len(password or "") < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(status_code=400, detail="weak_password")


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    identity = verify_admin_credentials(req.username, req.password)
    if not identity:
        raise HTTPException(status_code=401, detail="invalid_admin_credentials")
    token, expires_in = create_admin_access_token(identity)
    _write_admin_log("admin_login", {"username": identity.username, "role": identity.role})
    return {
        "status": "success",
        "token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "role": identity.role,
        "username": identity.username,
    }


@router.get("/admin/session")
async def admin_session(identity: AdminIdentity = Depends(get_current_admin)):
    return {"username": identity.username, "role": identity.role}


@router.get("/admin/users")
async def admin_users(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, first_name, last_name, phone_number, national_id, dob,
                      bank_card_number, kyc_status, verification_level
               FROM users ORDER BY id DESC"""
        ).fetchall()
    return {
        "users": [
            {
                "id": row["id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "phone_number": row["phone_number"],
                "national_id": _mask_national_id(row["national_id"]),
                "dob": row["dob"],
                "bank_card_number": _mask_card(row["bank_card_number"]),
                "kyc_status": row["kyc_status"],
                "verification_level": int(row["verification_level"] or 1),
            }
            for row in rows
        ]
    }


@router.get("/admin/users/{user_id}")
async def admin_user_details(user_id: int, identity: AdminIdentity = Depends(WRITE_ROLES)):
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, first_name, last_name, phone_number, national_id, dob,
                      bank_card_number, kyc_status, verification_level
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    _write_admin_log("view_user_sensitive_details", {"user_id": user_id, "viewer": identity.username})
    return {"user": dict(row)}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, identity: AdminIdentity = Depends(ADMIN_ONLY)):
    with get_db() as conn:
        user = conn.execute("SELECT id, phone_number FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        if _table_exists(conn, "kyc_submissions"):
            conn.execute("DELETE FROM kyc_submissions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM bank_cards WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM password_reset_tokens WHERE phone_number = ?", (user["phone_number"],))
        if _table_exists(conn, "telegram_link_tokens"):
            conn.execute("DELETE FROM telegram_link_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _write_admin_log("delete_user", {"user_id": user_id, "admin": identity.username})
    return {"status": "deleted"}


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(
    user_id: int,
    req: AdminResetPasswordRequest,
    identity: AdminIdentity = Depends(WRITE_ROLES),
):
    _validate_new_password(req.new_password)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="user_not_found")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(req.new_password), user_id))
    _write_admin_log("reset_user_password", {"user_id": user_id, "admin": identity.username})
    return {"status": "success"}


@router.get("/admin/faqs")
async def admin_get_faqs(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        rows = conn.execute("SELECT id, question, answer, created_at FROM faqs ORDER BY id DESC").fetchall()
    return {"faqs": [dict(row) for row in rows]}


@router.post("/admin/faqs")
async def admin_add_faq(req: FaqRequest, identity: AdminIdentity = Depends(WRITE_ROLES)):
    question = req.question.strip()
    answer = req.answer.strip()
    if not question or not answer:
        raise HTTPException(status_code=400, detail="question_and_answer_required")
    with get_db() as conn:
        conn.execute("INSERT INTO faqs (question, answer) VALUES (?, ?)", (question, answer))
    _write_admin_log("add_faq", {"admin": identity.username})
    return {"status": "created"}


@router.delete("/admin/faqs/{faq_id}")
async def admin_delete_faq(faq_id: int, identity: AdminIdentity = Depends(WRITE_ROLES)):
    with get_db() as conn:
        conn.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
    _write_admin_log("delete_faq", {"faq_id": faq_id, "admin": identity.username})
    return {"status": "deleted"}


@router.get("/admin/logs")
async def admin_logs(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        rows = conn.execute("SELECT id, action, details, created_at FROM admin_logs ORDER BY id DESC LIMIT 300").fetchall()
    return {"logs": [dict(row) for row in rows]}


@router.get("/admin/activity-logs")
async def admin_activity_logs(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, user_id, phone_number, action, source, details, created_at
               FROM user_activity_logs ORDER BY id DESC LIMIT 1000"""
        ).fetchall()
    return {"logs": [dict(row) for row in rows]}


@router.get("/admin/kyc-logs")
async def admin_kyc_logs(identity: AdminIdentity = Depends(WRITE_ROLES)):
    with get_db() as conn:
        ehraz_rows = conn.execute(
            """SELECT id, phone_number, national_id, endpoint, success, error_message, created_at
               FROM ehraz_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        sms_rows = conn.execute(
            """SELECT id, phone_number, provider, success, error_message, created_at
               FROM sms_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        verification_rows = conn.execute(
            """SELECT id, phone_number, national_id, action, details, created_at
               FROM kyc_verification_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
    return {
        "ehraz_logs": [dict(row) for row in ehraz_rows],
        "sms_logs": [dict(row) for row in sms_rows],
        "kyc_verification_logs": [dict(row) for row in verification_rows],
    }


@router.post("/admin/messages/send")
async def admin_send_message(req: AdminMessageRequest, identity: AdminIdentity = Depends(WRITE_ROLES)):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message_required")
    with get_db() as conn:
        if req.user_id is not None:
            rows = conn.execute("SELECT id FROM users WHERE id = ?", (req.user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM users ORDER BY id DESC").fetchall()
    sent = 0
    for row in rows:
        if await send_user_message(int(row["id"]), message):
            sent += 1
    _write_admin_log(
        "admin_send_message",
        {"user_id": req.user_id, "sent": sent, "requested": len(rows), "admin": identity.username},
    )
    return {"status": "success", "sent": sent, "requested": len(rows)}


@router.get("/admin/transactions")
async def admin_list_transactions(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, user_name, user_phone, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp, receipt_photo_url,
                      receipt_description, payment_link, expires_at
               FROM transactions ORDER BY id DESC LIMIT 500"""
        ).fetchall()
    return {"transactions": [dict(row) for row in rows]}


@router.get("/admin/reports")
async def admin_reports(identity: AdminIdentity = Depends(READ_ROLES)):
    with get_db() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS total_orders,
                      SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done_orders,
                      SUM(CASE WHEN status LIKE 'Canceled%' THEN 1 ELSE 0 END) AS canceled_orders,
                      SUM(send_amount) AS total_send_amount
               FROM transactions"""
        ).fetchone()
    return {"report": dict(totals)}


@router.post("/admin/transactions/{reference_number}/update-status")
async def admin_update_transaction_status(
    reference_number: str,
    req: StatusUpdateRequest,
    identity: AdminIdentity = Depends(WRITE_ROLES),
):
    if req.status not in VALID_TRANSACTION_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_status")
    with get_db() as conn:
        transaction = conn.execute(
            "SELECT id, user_id FROM transactions WHERE reference_number = ?",
            (reference_number,),
        ).fetchone()
        if not transaction:
            raise HTTPException(status_code=404, detail="transaction_not_found")
        conn.execute(
            """UPDATE transactions
               SET status = ?, receipt_photo_url = ?, receipt_description = ?, payment_link = ?, status_updated_at = ?
               WHERE reference_number = ?""",
            (
                req.status,
                req.receipt_photo_url,
                req.receipt_description,
                req.payment_link,
                datetime.now(timezone.utc).isoformat(),
                reference_number,
            ),
        )
    await send_user_message(
        int(transaction["user_id"]),
        f"وضعیت سفارش #{reference_number} تغییر کرد:\n{req.status}",
    )
    await send_admin_message(
        "🔔 <b>تغییر وضعیت سفارش</b>\n"
        f"🔢 شماره پیگیری: {html.escape(reference_number)}\n"
        f"📌 وضعیت جدید: {html.escape(req.status)}\n"
        f"👮 ادمین: {html.escape(identity.username)}\n"
        f"⏰ زمان: {now_text()}"
    )
    _write_admin_log(
        "transaction_status_updated",
        {"reference_number": reference_number, "status": req.status, "admin": identity.username},
    )
    return {"status": "success"}


@router.get("/admin/rates")
async def admin_get_rates(identity: AdminIdentity = Depends(READ_ROLES)):
    settings = rates_api.get_rate_settings()
    snapshot = await rates_api._admin_rate_snapshot(settings)
    return {"settings": settings, **snapshot}


@router.post("/admin/rates")
async def admin_update_rates(req: AdminRateSettings, identity: AdminIdentity = Depends(ADMIN_ONLY)):
    values = req.model_dump()
    for key, value in values.items():
        numeric = float(value)
        if key.endswith("_percentage") and not (-50.0 <= numeric <= 50.0):
            raise HTTPException(status_code=400, detail=f"invalid_percentage:{key}")
        if key.endswith("_manual_rate") and numeric < 0:
            raise HTTPException(status_code=400, detail=f"invalid_manual_rate:{key}")
    rates_api._ensure_schema()
    with get_db() as conn:
        for key, value in values.items():
            conn.execute(
                f"""INSERT INTO {rates_api.RATE_SETTINGS_TABLE} (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
                (key, float(value)),
            )
    _write_admin_log("rate_settings_updated", {"admin": identity.username})
    settings = rates_api.get_rate_settings()
    snapshot = await rates_api._admin_rate_snapshot(settings)
    return {"status": "success", "settings": settings, **snapshot}


@router.get("/admin/kyc/submissions")
async def admin_list_kyc_submissions(
    status: str | None = None,
    identity: AdminIdentity = Depends(WRITE_ROLES),
):
    _ensure_kyc_schema()
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
    return {"submissions": [_submission_dict(row) for row in rows]}


@router.get("/admin/kyc/submissions/{submission_id}/file/{kind}")
async def admin_kyc_file(
    submission_id: int,
    kind: str,
    identity: AdminIdentity = Depends(WRITE_ROLES),
):
    if kind not in {"front", "back", "selfie"}:
        raise HTTPException(status_code=400, detail="invalid_file_kind")
    _ensure_kyc_schema()
    column = {"front": "front_path", "back": "back_path", "selfie": "selfie_path"}[kind]
    with get_db() as conn:
        row = conn.execute(
            f"SELECT user_id, {column} AS path FROM kyc_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
    if not row or not row["path"]:
        raise HTTPException(status_code=404, detail="file_not_found")
    file_path = Path(row["path"]).resolve()
    upload_root = kyc_api.UPLOAD_ROOT.resolve()
    if upload_root not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file_not_found")
    _write_admin_log(
        "view_kyc_document",
        {"submission_id": submission_id, "user_id": row["user_id"], "kind": kind, "admin": identity.username},
    )
    return FileResponse(
        path=str(file_path),
        media_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
        headers={"Cache-Control": "no-store, private", "Pragma": "no-cache"},
    )


@router.post("/admin/kyc/submissions/{submission_id}/approve")
async def admin_approve_kyc(
    submission_id: int,
    req: KycDecisionRequest,
    identity: AdminIdentity = Depends(ADMIN_ONLY),
):
    _ensure_kyc_schema()
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
            """UPDATE kyc_submissions
               SET status='approved', rejection_reason=NULL, reviewed_by=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (identity.username, submission_id),
        )
        conn.execute(
            """UPDATE users
               SET verification_level = CASE WHEN verification_level < ? THEN ? ELSE verification_level END,
                   kyc_status='Approved'
               WHERE id=?""",
            (level, level, submission["user_id"]),
        )
    _write_admin_log(
        "kyc_approved",
        {"submission_id": submission_id, "level": level, "user_id": submission["user_id"], "admin": identity.username},
    )
    await send_admin_message(f"✅ KYC سطح {level} | Submission #{submission_id} => approved")
    return {"status": "approved", "verification_level": level}


@router.post("/admin/kyc/submissions/{submission_id}/reject")
async def admin_reject_kyc(
    submission_id: int,
    req: KycDecisionRequest,
    identity: AdminIdentity = Depends(ADMIN_ONLY),
):
    reason = (req.reason or "مدارک قابل تایید نیست؛ لطفاً دوباره بارگذاری کنید.").strip()
    _ensure_kyc_schema()
    with get_db() as conn:
        submission = conn.execute("SELECT * FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="submission_not_found")
        if submission["status"] != "pending":
            raise HTTPException(status_code=409, detail="submission_already_reviewed")
        level = int(submission["level"])
        conn.execute(
            """UPDATE kyc_submissions
               SET status='rejected', rejection_reason=?, reviewed_by=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (reason, identity.username, submission_id),
        )
    _write_admin_log(
        "kyc_rejected",
        {"submission_id": submission_id, "level": level, "user_id": submission["user_id"], "admin": identity.username},
    )
    await send_admin_message(f"❌ KYC سطح {level} | Submission #{submission_id} => rejected")
    return {"status": "rejected", "reason": reason}
