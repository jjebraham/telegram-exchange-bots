import logging
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db, get_db
from .auth import verify_admin_token
from .api import auth, users, kyc, faq, rates, transactions, chatbot, broadcast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Kiani Exchange API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api", tags=["Authentication"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(kyc.router, prefix="/api", tags=["KYC"])
app.include_router(faq.router, prefix="/api", tags=["FAQ"])
app.include_router(rates.router, prefix="/api", tags=["Rates"])
app.include_router(transactions.router, prefix="/api", tags=["Transactions"])
app.include_router(chatbot.router, prefix="/api", tags=["Chatbot"])
app.include_router(broadcast.router, prefix="/api", tags=["Broadcast"])


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("Kiani Exchange API started")


@app.get("/")
async def root():
    return {"message": "Kiani Exchange API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/admin/stats")
async def admin_stats(_admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        total_users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        pending_kyc = db.execute("SELECT COUNT(*) as c FROM users WHERE kyc_status = 'Pending' AND national_id IS NOT NULL").fetchone()["c"]
        approved_kyc = db.execute("SELECT COUNT(*) as c FROM users WHERE kyc_status = 'Approved'").fetchone()["c"]
        rejected_kyc = db.execute("SELECT COUNT(*) as c FROM users WHERE kyc_status = 'Rejected'").fetchone()["c"]
        total_transactions = db.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
        total_faqs = db.execute("SELECT COUNT(*) as c FROM faqs").fetchone()["c"]
        total_chats = db.execute("SELECT COUNT(*) as c FROM chatbot_logs").fetchone()["c"]

        return {
            "total_users": total_users,
            "pending_kyc": pending_kyc,
            "approved_kyc": approved_kyc,
            "rejected_kyc": rejected_kyc,
            "total_transactions": total_transactions,
            "total_faqs": total_faqs,
            "total_chats": total_chats,
        }
    finally:
        db.close()


@app.get("/api/admin/logs")
async def get_admin_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _admin: dict = Depends(verify_admin_token)
):
    db = get_db()
    try:
        offset = (page - 1) * limit
        total = db.execute("SELECT COUNT(*) as c FROM admin_logs").fetchone()["c"]
        rows = db.execute(
            "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return {
            "logs": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1,
        }
    finally:
        db.close()
