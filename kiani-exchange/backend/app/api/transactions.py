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
    # Optional manual payload (server also backfills from DB)
    national_id: Optional[str] = None
    date_of_birth: Optional[str] = None
    bank_card_number: Optional[str] = None


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
    national_id = req.national_id
    date_of_birth = req.date_of_birth
    bank_card_number = req.bank_card_number

    with get_db() as conn:
        user_row = conn.execute(
            "SELECT national_id, dob, bank_card_number FROM users WHERE phone_number = ?",
            (req.user_phone,),
        ).fetchone()
        if user_row:
            national_id = user_row["national_id"]
            date_of_birth = user_row["dob"]
            bank_card_number = user_row["bank_card_number"]

    # Build message with user's 3 factors for admin
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
    
    # Add user's 3 factors if available (for admin only)
    if national_id or date_of_birth or bank_card_number:
        message += "\n\n🔐 اطلاعات احراز کاربر:\n"
        if national_id:
            message += f"🆔 کدملی: {national_id}\n"
        if date_of_birth:
            message += f"📅 تاریخ تولد: {date_of_birth}\n"
        if bank_card_number:
            message += f"💳 شماره کارت: {bank_card_number}"

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


@router.post("/transactions/{reference_number}/cancel")
async def cancel_transaction(
    reference_number: str,
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        # Check if transaction exists and belongs to user
        transaction = conn.execute(
            """SELECT id, status FROM transactions 
               WHERE reference_number = ? AND user_id = ?""",
            (reference_number, user_id),
        ).fetchone()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        # Update status to "Canceled by User"
        conn.execute(
            """UPDATE transactions 
               SET status = 'Canceled by User'
               WHERE reference_number = ? AND user_id = ?""",
            (reference_number, user_id),
        )
        conn.commit()
    
    return {"status": "success", "message": "Transaction canceled"}


@router.post("/admin/transactions/{reference_number}/update-status")
async def update_transaction_status(
    reference_number: str,
    status: str,
    admin_password: str,  # Simple admin auth
):
    # Simple admin authentication
    if admin_password != "admin123":  # Change this to a secure password
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    valid_statuses = [
        "Pending",
        "Under Review",
        "Waiting for User's Payment",
        "Waiting for Admin to Pay",
        "Under Process",
        "Done",
        "Rejected",
        "Canceled by Admin"
    ]
    
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    with get_db() as conn:
        # Check if transaction exists
        transaction = conn.execute(
            """SELECT id, user_id FROM transactions 
               WHERE reference_number = ?""",
            (reference_number,),
        ).fetchone()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        # Update status
        conn.execute(
            """UPDATE transactions 
               SET status = ?
               WHERE reference_number = ?""",
            (status, reference_number),
        )
        conn.commit()
        
        # Get user info for notification
        user = conn.execute(
            """SELECT phone_number FROM users WHERE id = ?""",
            (transaction["user_id"],),
        ).fetchone()
    
    # TODO: Send notification to user about status change
    # This would require a separate user notification system
    
    return {"status": "success", "message": f"Transaction status updated to {status}"}


@router.get("/admin/transactions")
async def admin_list_transactions(username: str, password: str):
    if username != "admin" or password != "admin123":
        raise HTTPException(status_code=401, detail="Unauthorized")
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, user_name, user_phone, exchange_pair, exchange_type, send_amount,
                      receive_amount, reference_number, status, timestamp, expires_at
               FROM transactions ORDER BY id DESC LIMIT 500"""
        ).fetchall()
    return {"transactions": [dict(row) for row in rows]}


@router.get("/admin/reports")
async def admin_reports(username: str, password: str):
    if username != "admin" or password != "admin123":
        raise HTTPException(status_code=401, detail="Unauthorized")
    with get_db() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS total_orders,
                      SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done_orders,
                      SUM(CASE WHEN status LIKE 'Canceled%' THEN 1 ELSE 0 END) AS canceled_orders,
                      SUM(send_amount) AS total_send_amount
               FROM transactions"""
        ).fetchone()
    return {"report": dict(totals)}
