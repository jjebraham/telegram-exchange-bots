import html
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..admin_notify import now_text, send_admin_message
from ..auth import get_current_user_id
from ..database import get_db
from ..exchange_math import calculate_order
from .rates import get_effective_rates

logger = logging.getLogger(__name__)
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


@router.post("/transactions")
async def create_transaction(
    req: TransactionRequest,
    user_id: int = Depends(get_current_user_id),
):
    rates, _settings, _usdt_irr, _usdt_try = await get_effective_rates()
    calculated = calculate_order(req.exchange_type, req.send_amount, rates)

    if req.exchange_type in {"sell_usdt", "convert_usdt_to_lira"} and calculated.net_send_amount <= 0:
        raise HTTPException(status_code=400, detail="send_amount_too_low_for_fee")

    if not req.reference_number.strip():
        raise HTTPException(status_code=400, detail="reference_number_required")

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
            raise HTTPException(status_code=409, detail="duplicate_reference_number")

        # The backend is authoritative for user identity, verification level and
        # calculated receive amount. Client-supplied copies are intentionally ignored.
        conn.execute(
            """INSERT INTO transactions
               (user_id, user_name, user_phone, verification_level,
                exchange_pair, exchange_type, send_amount, receive_amount,
                reference_number, status, timestamp, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)""",
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
async def get_user_transactions(user_id: int = Depends(get_current_user_id)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp,
                      receipt_photo_url, receipt_description, payment_link
               FROM transactions
               WHERE user_id = ?
               ORDER BY id DESC""",
            (user_id,),
        ).fetchall()

    return {
        "transactions": [
            {
                "id": row["id"],
                "exchange_pair": row["exchange_pair"],
                "exchange_type": row["exchange_type"],
                "send_amount": row["send_amount"],
                "receive_amount": row["receive_amount"],
                "reference_number": row["reference_number"],
                "status": row["status"],
                "timestamp": row["timestamp"],
                "receipt_photo_url": row["receipt_photo_url"],
                "receipt_description": row["receipt_description"],
                "payment_link": row["payment_link"],
            }
            for row in rows
        ]
    }


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
            raise HTTPException(status_code=404, detail="transaction_not_found")
        if transaction["status"] in {"Done", "Rejected", "Canceled by Admin", "Canceled by User", "Expired"}:
            raise HTTPException(status_code=409, detail="transaction_not_cancelable")

        conn.execute(
            """UPDATE transactions
               SET status = 'Canceled by User', status_updated_at = CURRENT_TIMESTAMP
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
        f"🔢 شماره پیگیری: {html.escape(reference_number)}\n"
        f"⏰ زمان: {now_text()}"
    )
    return {"status": "success", "message": "Transaction canceled"}
