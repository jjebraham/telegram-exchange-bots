import aiohttp
import html
import logging
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..auth import get_current_user_id
from ..exchange_math import calculate_order
from ..admin_notify import now_text, send_admin_message
from .rates import get_effective_rates

logger = logging.getLogger(__name__)

ADMIN_BOT_TOKEN = (
    os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0") or 0)
PROXY_URL = os.getenv("TRANSACTION_PROXY_URL", "").strip() or None

router = APIRouter()


class TransactionRequest(BaseModel):
    user_name: str
    user_phone: str
    verification_level: int
    exchange_pair: str
    exchange_type: str
    send_amount: float
    receive_amount: float
    reference_number: str
    timestamp: str
    status: str
    expires_at: str
    fee: Optional[float] = None
    total_amount: Optional[float] = None


class NotifyTransactionRequest(BaseModel):
    user_name: str
    user_phone: str
    verification_level: int
    exchange_pair: str
    send_amount: float
    receive_amount: float
    reference_number: str
    timestamp: str
    expires_at: str
    fee: Optional[float] = None
    total_amount: Optional[float] = None
    national_id: Optional[str] = None
    date_of_birth: Optional[str] = None
    bank_card_number: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    username: str
    password: str
    status: str
    receipt_photo_url: Optional[str] = None
    receipt_description: Optional[str] = None
    payment_link: Optional[str] = None


async def _send_telegram_message(chat_id: int, message: str):
    if not ADMIN_BOT_TOKEN:
        logger.warning("Telegram bot token is not configured; skipping Telegram message")
        return
    admin_url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    async with aiohttp.ClientSession() as session:
        await session.post(
            admin_url,
            json=payload,
            proxy=PROXY_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        )


async def _notify_status_change(user_id: int, reference_number: str, status: str):
    # Keep the legacy user notification attempt, but always send the admin event
    # through the dedicated admin notification path as well.
    msg = f"📌 وضعیت سفارش #{reference_number} تغییر کرد:\n{status}"
    try:
        await _send_telegram_message(user_id, msg)
    except Exception:
        pass

    await send_admin_message(
        "🔔 <b>تغییر وضعیت سفارش</b>\n"
        f"🔢 شماره پیگیری: {html.escape(reference_number)}\n"
        f"📌 وضعیت جدید: {html.escape(status)}\n"
        f"⏰ زمان: {now_text()}"
    )


def _admin_role(username: str, password: str) -> str | None:
    admin_user = os.getenv("ADMIN_PANEL_USERNAME", "").strip()
    admin_pass = os.getenv("ADMIN_PANEL_PASSWORD", "")
    support_user = os.getenv("SUPPORT_PANEL_USERNAME", "").strip()
    support_pass = os.getenv("SUPPORT_PANEL_PASSWORD", "")
    viewer_user = os.getenv("VIEWER_PANEL_USERNAME", "").strip()
    viewer_pass = os.getenv("VIEWER_PANEL_PASSWORD", "")

    if admin_user and admin_pass and username == admin_user and password == admin_pass:
        return "admin"
    if support_user and support_pass and username == support_user and password == support_pass:
        return "support"
    if viewer_user and viewer_pass and username == viewer_user and password == viewer_pass:
        return "viewer"
    return None


def _require_roles(username: str, password: str, allowed: set[str]) -> str:
    role = _admin_role(username, password)
    if role not in allowed:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return role


@router.post("/transactions")
async def create_transaction(
    req: TransactionRequest,
    user_id: int = Depends(get_current_user_id),
):
    rates, _settings, _usdt_irr, _usdt_try = await get_effective_rates()
    calculated = calculate_order(req.exchange_type, req.send_amount, rates)

    if req.exchange_type in {"sell_usdt", "convert_usdt_to_lira"} and calculated.net_send_amount <= 0:
        raise HTTPException(status_code=400, detail="send_amount_too_low_for_fee")

    with get_db() as conn:
        user = conn.execute(
            """SELECT id, first_name, last_name, phone_number, national_id, dob,
                      bank_card_number, verification_level
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")

        existing = conn.execute(
            "SELECT id FROM transactions WHERE reference_number = ?",
            (req.reference_number,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Duplicate reference number")

        conn.execute(
            """INSERT INTO transactions
               (user_id, user_name, user_phone, verification_level,
                exchange_pair, exchange_type, send_amount, receive_amount,
                reference_number, status, timestamp, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                f"{user['first_name']} {user['last_name']}",
                user["phone_number"],
                int(user["verification_level"] or 1),
                req.exchange_pair,
                req.exchange_type,
                req.send_amount,
                calculated.receive_amount,
                req.reference_number,
                req.status,
                req.timestamp,
                req.expires_at,
            ),
        )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("user_created_order", f"user_id={user_id};ref={req.reference_number};pair={req.exchange_pair}"),
        )

    notification = (
        "🆕 <b>درخواست معامله جدید</b>\n\n"
        f"👤 نام: {html.escape(str(user['first_name']))} {html.escape(str(user['last_name']))}\n"
        f"📱 شماره: {html.escape(str(user['phone_number']))}\n"
        f"✅ سطح احراز: {int(user['verification_level'] or 1)}\n"
        f"💱 نوع معامله: {html.escape(req.exchange_pair)}\n"
        f"💵 مبلغ ارسال: {req.send_amount:,.4f}\n"
        f"💰 مبلغ دریافت: {calculated.receive_amount:,.4f}\n"
        f"💸 کارمزد: {calculated.fee_amount:,.4f} {html.escape(calculated.fee_currency)}\n"
        f"🔢 شماره پیگیری: {html.escape(req.reference_number)}\n"
        f"🆔 کد ملی: {html.escape(str(user['national_id'] or '-'))}\n"
        f"💳 کارت: {html.escape(str(user['bank_card_number'] or '-'))}\n"
        f"⏰ زمان: {now_text()}"
    )
    notified = await send_admin_message(notification)
    if not notified:
        logger.error("Order %s was created but admin Telegram notification failed", req.reference_number)

    return {
        "status": "success",
        "reference_number": req.reference_number,
        "receive_amount": calculated.receive_amount,
        "fee": calculated.fee_amount,
        "fee_currency": calculated.fee_currency,
        "net_send_amount": calculated.net_send_amount,
        "admin_notified": notified,
    }


@router.get("/user/transactions")
async def get_user_transactions(
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp, receipt_photo_url, receipt_description, payment_link
               FROM transactions
               WHERE user_id = ?
               ORDER BY id DESC""",
            (user_id,),
        ).fetchall()

    transactions = [
        {
            "id": row["id"],
            "exchange_pair": row["exchange_pair"],
            "send_amount": row["send_amount"],
            "receive_amount": row["receive_amount"],
            "reference_number": row["reference_number"],
            "status": row["status"],
            "timestamp": row["timestamp"],
            "receipt_photo_url": row["receipt_photo_url"] if "receipt_photo_url" in row.keys() else None,
            "receipt_description": row["receipt_description"] if "receipt_description" in row.keys() else None,
            "payment_link": row["payment_link"] if "payment_link" in row.keys() else None,
        }
        for row in rows
    ]

    return {"transactions": transactions}


@router.post("/admin/notify-transaction")
async def notify_admin_transaction(req: NotifyTransactionRequest):
    # Kept for backwards compatibility with older frontend builds. New order
    # notifications are sent atomically from POST /transactions after the DB insert.
    return {"status": "already_notified_by_create_transaction", "reference_number": req.reference_number}


@router.post("/transactions/{reference_number}/cancel")
async def cancel_transaction(
    reference_number: str,
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        transaction = conn.execute(
            """SELECT id, status, user_name, user_phone FROM transactions
               WHERE reference_number = ? AND user_id = ?""",
            (reference_number, user_id),
        ).fetchone()

        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")

        conn.execute(
            """UPDATE transactions
               SET status = 'Canceled by User'
               WHERE reference_number = ? AND user_id = ?""",
            (reference_number, user_id),
        )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("user_canceled_order", f"user_id={user_id};ref={reference_number}"),
        )

    await send_admin_message(
        "❌ <b>لغو سفارش توسط کاربر</b>\n"
        f"👤 {html.escape(str(transaction['user_name'] or '-'))}\n"
        f"📱 {html.escape(str(transaction['user_phone'] or '-'))}\n"
        f"🔢 شماره پیگیری: {html.escape(reference_number)}\n"
        f"⏰ زمان: {now_text()}"
    )
    return {"status": "success", "message": "Transaction canceled"}


@router.post("/admin/transactions/{reference_number}/update-status")
async def update_transaction_status(reference_number: str, req: StatusUpdateRequest):
    _require_roles(req.username, req.password, {"admin", "support"})

    valid_statuses = [
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
    ]

    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    with get_db() as conn:
        transaction = conn.execute(
            """SELECT id, user_id FROM transactions
               WHERE reference_number = ?""",
            (reference_number,),
        ).fetchone()
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")

        conn.execute(
            """UPDATE transactions
               SET status = ?, receipt_photo_url = ?, receipt_description = ?, payment_link = ?, status_updated_at = ?
               WHERE reference_number = ?""",
            (req.status, req.receipt_photo_url, req.receipt_description, req.payment_link, datetime.utcnow().isoformat(), reference_number),
        )

    await _notify_status_change(transaction["user_id"], reference_number, req.status)
    return {"status": "success", "message": f"Transaction status updated to {req.status}"}


@router.get("/admin/transactions")
async def admin_list_transactions(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, user_name, user_phone, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp, receipt_photo_url, receipt_description, payment_link, expires_at
               FROM transactions ORDER BY id DESC LIMIT 500"""
        ).fetchall()
    return {"transactions": [dict(row) for row in rows]}


@router.get("/admin/reports")
async def admin_reports(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS total_orders,
                      SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done_orders,
                      SUM(CASE WHEN status LIKE 'Canceled%' THEN 1 ELSE 0 END) AS canceled_orders,
                      SUM(send_amount) AS total_send_amount
               FROM transactions"""
        ).fetchone()
    return {"report": dict(totals)}
