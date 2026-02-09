import aiohttp
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..auth import get_current_user_id

ADMIN_BOT_TOKEN = "8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU"
ADMIN_CHAT_ID = 2043363119
PROXY_URL = "http://jjebraham-25:Amir1234@p.webshare.io:80"

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


@router.post("/transactions")
async def create_transaction(
    req: TransactionRequest,
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        # Check for duplicate reference number
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
                req.user_name,
                req.user_phone,
                req.verification_level,
                req.exchange_pair,
                req.exchange_type,
                req.send_amount,
                req.receive_amount,
                req.reference_number,
                req.status,
                req.timestamp,
                req.expires_at,
            ),
        )
        conn.commit()

    return {"status": "success", "reference_number": req.reference_number}


@router.get("/user/transactions")
async def get_user_transactions(
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp
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
        }
        for row in rows
    ]

    return {"transactions": transactions}


@router.post("/admin/notify-transaction")
async def notify_admin_transaction(req: NotifyTransactionRequest):
    message = (
        "🆕 درخواست معامله جدید\n\n"
        f"👤 نام: {req.user_name}\n"
        f"📱 شماره: {req.user_phone}\n"
        f"✅ سطح احراز: {req.verification_level}\n"
        f"💱 نوع معامله: {req.exchange_pair}\n"
        f"💵 ارسال: {req.send_amount}\n"
        f"💰 دریافت: {req.receive_amount}\n"
        f"🔢 شماره پیگیری: {req.reference_number}\n"
        f"📅 تاریخ: {req.timestamp}\n"
        f"⏰ انقضا: {req.expires_at}"
    )

    admin_url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                admin_url,
                json=payload,
                proxy=PROXY_URL,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=502,
                        detail="Failed to notify admin",
                    )
    except aiohttp.ClientError:
        raise HTTPException(
            status_code=502,
            detail="Failed to connect to Telegram",
        )

    return {"status": "sent"}
