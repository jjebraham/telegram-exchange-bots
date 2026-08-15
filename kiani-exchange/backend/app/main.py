import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Always load the backend .env from its known location before importing modules
# that read configuration at import time. Use override=True so stale variables
# inherited by a long-running Supervisor daemon cannot mask the current .env.
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env", override=True)

# KYC documents contain highly sensitive identity data. Use a restrictive process
# umask so newly created runtime files are private to the service account by default.
os.umask(0o077)

# Keep the normal user bot token separate from the dedicated admin bot token.
# Older backend helpers may still read TELEGRAM_BOT_TOKEN, so map the admin token
# only for this FastAPI process when a dedicated admin token is configured.
admin_bot_token = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
if admin_bot_token:
    os.environ["TELEGRAM_BOT_TOKEN"] = admin_bot_token

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .api import rates, users, transactions, kyc, activity
from .price_cache import price_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Exchange API",
    description="Backend API for the Telegram Mini App",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rates.router, prefix="/api", tags=["rates"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(transactions.router, prefix="/api", tags=["transactions"])
app.include_router(kyc.router, prefix="/api", tags=["kyc"])
app.include_router(activity.router, prefix="/api", tags=["activity"])


@app.on_event("startup")
async def startup():
    init_db()
    await price_cache.warm_cache()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
