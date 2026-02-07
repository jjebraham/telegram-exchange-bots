from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
import jwt
import bcrypt
from pydantic import BaseModel
import os

from .database import (
    get_db,
    init_db,
    User,
    Admin,
    Transaction,
    FAQ,
    ExchangeRate,
    AdminLog,
    BroadcastMessage,
    ChatbotLog,
    PriceAlert,
    SupportTicket,
)
from .services.price_service import PriceService
from .services.kyc_service import KYCService
from .services.ai_service import AIService

app = FastAPI(title="Kiani Exchange API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

security = HTTPBearer()

price_service = PriceService()
kyc_service = KYCService()
ai_service = AIService()


@app.on_event("startup")
async def startup_event():
    init_db()
    print("✅ Database initialized")


class UserAuth(BaseModel):
    telegram_id: int
    first_name: str
    last_name: Optional[str]


class AdminLogin(BaseModel):
    username: str
    password: str


class TransactionCreate(BaseModel):
    transaction_type: str
    from_currency: str
    to_currency: str
    amount: float


class FAQCreate(BaseModel):
    question_fa: str
    answer_fa: str
    question_en: Optional[str]
    answer_en: Optional[str]
    category: str
    order: int = 0


class FAQUpdate(BaseModel):
    question_fa: Optional[str]
    answer_fa: Optional[str]
    question_en: Optional[str]
    answer_en: Optional[str]
    category: Optional[str]
    order: Optional[int]
    is_active: Optional[bool]


class BroadcastCreate(BaseModel):
    message: str
    target_group: str
    scheduled_at: Optional[datetime]


class ChatbotQuery(BaseModel):
    question: str
    user_id: Optional[int]


class PriceAlertCreate(BaseModel):
    currency_pair: str
    target_price: float
    condition: str


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    payload = verify_token(credentials)
    admin_id = payload.get("admin_id")
    if not admin_id:
        raise HTTPException(status_code=403, detail="Not an admin")
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=403, detail="Admin not found or inactive")
    return admin


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@app.post("/api/auth/telegram")
async def telegram_auth(user_auth: UserAuth, db: Session = Depends(get_db)):
    """Authenticate user via Telegram"""
    user = db.query(User).filter(User.telegram_id == user_auth.telegram_id).first()

    if not user:
        return {"status": "not_registered", "message": "User not found"}

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        {"user_id": user.id, "telegram_id": user.telegram_id}
    )

    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "kyc_status": user.kyc_status,
            "verification_level": user.verification_level,
        },
    }


@app.get("/api/user/profile")
async def get_user_profile(
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get user profile"""
    user = db.query(User).filter(User.id == token_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "kyc_status": user.kyc_status,
        "verification_level": user.verification_level,
        "referral_code": user.referral_code,
        "created_at": user.created_at,
    }


@app.get("/api/user/transactions")
async def get_user_transactions(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get user transactions"""
    query = db.query(Transaction).filter(Transaction.user_id == token_data["user_id"])

    if status:
        query = query.filter(Transaction.status == status)

    transactions = (
        query.order_by(Transaction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "transactions": [
            {
                "id": t.id,
                "transaction_type": t.transaction_type,
                "from_currency": t.from_currency,
                "to_currency": t.to_currency,
                "amount": t.amount,
                "rate": t.rate,
                "fee": t.fee,
                "total_amount": t.total_amount,
                "status": t.status,
                "reference_code": t.reference_code,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in transactions
        ]
    }


@app.post("/api/user/transactions")
async def create_transaction(
    transaction: TransactionCreate,
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a new transaction"""
    import random

    rates = await price_service.get_all_rates()

    fee_percentage = 0.02 if "buy" in transaction.transaction_type else 0.03
    fee = transaction.amount * fee_percentage

    rate = 0
    if "lira" in transaction.transaction_type:
        rate = rates.get("USDT_TRY", 0)
    elif "usdt" in transaction.transaction_type:
        rate = rates.get("USDT_IRR", 0) / 10

    total_amount = transaction.amount * rate + fee

    new_transaction = Transaction(
        user_id=token_data["user_id"],
        transaction_type=transaction.transaction_type,
        from_currency=transaction.from_currency,
        to_currency=transaction.to_currency,
        amount=transaction.amount,
        rate=rate,
        fee=fee,
        total_amount=total_amount,
        reference_code=f"TXN{random.randint(100000, 999999)}",
        status="pending",
    )

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    return {"status": "success", "transaction": new_transaction}


@app.get("/api/rates/current")
async def get_current_rates():
    """Get current exchange rates"""
    rates = await price_service.get_all_rates()
    return {"rates": rates, "timestamp": datetime.utcnow()}


@app.get("/api/rates/history")
async def get_rate_history(
    currency_pair: str,
    days: int = 7,
    db: Session = Depends(get_db),
):
    """Get historical rates"""
    start_date = datetime.utcnow() - timedelta(days=days)

    rates = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.currency_pair == currency_pair,
            ExchangeRate.created_at >= start_date,
        )
        .order_by(ExchangeRate.created_at)
        .all()
    )

    return {
        "currency_pair": currency_pair,
        "data": [
            {"rate": r.rate, "timestamp": r.created_at}
            for r in rates
        ],
    }


@app.get("/api/calculator/fee")
async def calculate_fee(transaction_type: str, amount: float):
    """Calculate transaction fee"""
    rates = await price_service.get_all_rates()

    fee_percentage = 0.02 if "buy" in transaction_type else 0.03
    fee = amount * fee_percentage

    rate = 0
    if "lira" in transaction_type:
        rate = rates.get("USDT_TRY", 0)
        if "buy" in transaction_type:
            rate *= 1.02
        else:
            rate *= 0.97
    elif "usdt" in transaction_type:
        rate = rates.get("USDT_IRR", 0) / 10
        if "buy" in transaction_type:
            rate *= 1.01
        else:
            rate *= 0.99

    total = amount * rate

    return {
        "amount": amount,
        "rate": rate,
        "fee": fee,
        "fee_percentage": fee_percentage * 100,
        "total": total + fee,
        "transaction_type": transaction_type,
    }


@app.get("/api/converter")
async def convert_currency(from_currency: str, to_currency: str, amount: float):
    """Convert between currencies"""
    rates = await price_service.get_all_rates()

    converted_amount = 0
    rate_used = 0

    if from_currency == "IRR" and to_currency == "USDT":
        rate_used = rates.get("USDT_IRR", 0) / 10
        converted_amount = amount / rate_used
    elif from_currency == "USDT" and to_currency == "IRR":
        rate_used = rates.get("USDT_IRR", 0) / 10
        converted_amount = amount * rate_used
    elif from_currency == "TRY" and to_currency == "USDT":
        rate_used = rates.get("USDT_TRY", 0)
        converted_amount = amount / rate_used
    elif from_currency == "USDT" and to_currency == "TRY":
        rate_used = rates.get("USDT_TRY", 0)
        converted_amount = amount * rate_used
    elif from_currency == "IRR" and to_currency == "TRY":
        usdt_irr = rates.get("USDT_IRR", 0) / 10
        usdt_try = rates.get("USDT_TRY", 0)
        converted_amount = (amount / usdt_irr) * usdt_try
        rate_used = usdt_try / usdt_irr
    elif from_currency == "TRY" and to_currency == "IRR":
        usdt_irr = rates.get("USDT_IRR", 0) / 10
        usdt_try = rates.get("USDT_TRY", 0)
        converted_amount = (amount / usdt_try) * usdt_irr
        rate_used = usdt_irr / usdt_try

    return {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "amount": amount,
        "converted_amount": round(converted_amount, 2),
        "rate": rate_used,
    }


@app.get("/api/faqs")
async def get_faqs(
    category: Optional[str] = None,
    language: str = "fa",
    db: Session = Depends(get_db),
):
    """Get FAQs"""
    query = db.query(FAQ).filter(FAQ.is_active == True)

    if category:
        query = query.filter(FAQ.category == category)

    faqs = query.order_by(FAQ.order).all()

    return {
        "faqs": [
            {
                "id": f.id,
                "question": f.question_fa if language == "fa" else f.question_en,
                "answer": f.answer_fa if language == "fa" else f.answer_en,
                "category": f.category,
            }
            for f in faqs
        ]
    }


@app.post("/api/chatbot/ask")
async def ask_chatbot(query: ChatbotQuery, db: Session = Depends(get_db)):
    """Ask chatbot a question"""
    answer, confidence = await ai_service.get_answer(query.question, db)

    if query.user_id:
        log = ChatbotLog(
            user_id=query.user_id,
            question=query.question,
            answer=answer,
            confidence=confidence,
        )
        db.add(log)
        db.commit()

    return {
        "question": query.question,
        "answer": answer,
        "confidence": confidence,
    }


@app.post("/api/alerts")
async def create_price_alert(
    alert: PriceAlertCreate,
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a price alert"""
    new_alert = PriceAlert(
        user_id=token_data["user_id"],
        currency_pair=alert.currency_pair,
        target_price=alert.target_price,
        condition=alert.condition,
    )
    db.add(new_alert)
    db.commit()
    return {"status": "success", "alert_id": new_alert.id}


@app.get("/api/alerts")
async def get_price_alerts(
    token_data: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get user's price alerts"""
    alerts = (
        db.query(PriceAlert)
        .filter(
            PriceAlert.user_id == token_data["user_id"],
            PriceAlert.is_active == True,
        )
        .all()
    )

    return {"alerts": alerts}


@app.post("/api/admin/login")
async def admin_login(credentials: AdminLogin, db: Session = Depends(get_db)):
    """Admin login"""
    admin = db.query(Admin).filter(Admin.username == credentials.username).first()

    if not admin or not verify_password(credentials.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    admin.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token({"admin_id": admin.id, "role": admin.role})

    return {
        "token": token,
        "admin": {
            "id": admin.id,
            "username": admin.username,
            "full_name": admin.full_name,
            "role": admin.role,
        },
    }


@app.get("/api/admin/dashboard")
async def admin_dashboard(
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Get admin dashboard statistics"""
    total_users = db.query(User).count()
    pending_kyc = db.query(User).filter(User.kyc_status == "Pending").count()
    approved_kyc = db.query(User).filter(User.kyc_status == "Approved").count()

    today = datetime.utcnow().date()
    today_transactions = db.query(Transaction).filter(Transaction.created_at >= today).count()

    pending_transactions = (
        db.query(Transaction).filter(Transaction.status == "pending").count()
    )

    return {
        "stats": {
            "total_users": total_users,
            "pending_kyc": pending_kyc,
            "approved_kyc": approved_kyc,
            "today_transactions": today_transactions,
            "pending_transactions": pending_transactions,
        }
    }


@app.get("/api/admin/users")
async def get_all_users(
    skip: int = 0,
    limit: int = 50,
    kyc_status: Optional[str] = None,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Get all users (admin only)"""
    query = db.query(User)

    if kyc_status:
        query = query.filter(User.kyc_status == kyc_status)

    users = (
        query.order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    total = query.count()

    return {
        "users": [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone_number": u.phone_number,
                "kyc_status": u.kyc_status,
                "created_at": u.created_at,
            }
            for u in users
        ],
        "total": total,
    }


@app.post("/api/admin/kyc/{user_id}/approve")
async def approve_kyc(
    user_id: int,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Approve user KYC"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.kyc_status = "Approved"
    user.kyc_notified = False

    log = AdminLog(
        admin_id=admin.id,
        action_type="kyc_approve",
        target_user_id=user_id,
        details=f"KYC approved for user {user.first_name} {user.last_name}",
    )
    db.add(log)
    db.commit()

    return {"status": "success", "message": "KYC approved"}


@app.post("/api/admin/kyc/{user_id}/reject")
async def reject_kyc(
    user_id: int,
    reason: str,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Reject user KYC"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.kyc_status = "Rejected"
    user.kyc_notified = False

    log = AdminLog(
        admin_id=admin.id,
        action_type="kyc_reject",
        target_user_id=user_id,
        details=f"KYC rejected: {reason}",
    )
    db.add(log)
    db.commit()

    return {"status": "success", "message": "KYC rejected"}


@app.post("/api/admin/faq")
async def create_faq(
    faq: FAQCreate,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Create new FAQ (admin only)"""
    new_faq = FAQ(**faq.dict())
    db.add(new_faq)
    db.commit()
    db.refresh(new_faq)

    return {"status": "success", "faq_id": new_faq.id}


@app.put("/api/admin/faq/{faq_id}")
async def update_faq(
    faq_id: int,
    faq: FAQUpdate,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Update FAQ (admin only)"""
    existing_faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not existing_faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    for key, value in faq.dict(exclude_unset=True).items():
        setattr(existing_faq, key, value)

    db.commit()
    return {"status": "success"}


@app.delete("/api/admin/faq/{faq_id}")
async def delete_faq(
    faq_id: int,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Delete FAQ (admin only)"""
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    db.delete(faq)
    db.commit()
    return {"status": "success"}


@app.post("/api/admin/broadcast")
async def create_broadcast(
    broadcast: BroadcastCreate,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Create broadcast message"""
    new_broadcast = BroadcastMessage(
        admin_id=admin.id,
        message=broadcast.message,
        target_group=broadcast.target_group,
        scheduled_at=broadcast.scheduled_at,
        status="scheduled" if broadcast.scheduled_at else "draft",
    )
    db.add(new_broadcast)
    db.commit()

    return {"status": "success", "broadcast_id": new_broadcast.id}


@app.get("/api/admin/logs")
async def get_admin_logs(
    skip: int = 0,
    limit: int = 100,
    admin: Admin = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Get admin activity logs"""
    logs = (
        db.query(AdminLog)
        .order_by(AdminLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "logs": [
            {
                "id": l.id,
                "admin_id": l.admin_id,
                "action_type": l.action_type,
                "details": l.details,
                "created_at": l.created_at,
            }
            for l in logs
        ]
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
