import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Always load the backend .env from its known location before importing modules
# that read configuration at import time. Use override=True so stale variables
# inherited by a long-running Supervisor daemon cannot mask the current .env.
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env", override=True)

# KYC documents and profile images contain private user data. Use a restrictive
# process umask so newly created runtime files are private to the service account.
os.umask(0o077)

# Older admin-notification helpers still read TELEGRAM_BOT_TOKEN. Keep their
# compatibility mapping for now; the new customer-notification module reads the
# normal bot token separately from TELEGRAM_USER_BOT_TOKEN or the raw .env value.
admin_bot_token = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
if admin_bot_token:
    os.environ["TELEGRAM_BOT_TOKEN"] = admin_bot_token

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .api import rates, users, transactions, kyc, activity, profile
from .price_cache import price_cache
from .notification_watcher import notification_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Exchange API",
    description="Backend API for the Telegram Mini App",
    version="1.3.0",
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
app.include_router(profile.router, prefix="/api", tags=["profile"])

_notification_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _notification_task
    init_db()
    profile.ensure_profile_schema()
    await price_cache.warm_cache()
    _notification_task = asyncio.create_task(notification_watcher())


@app.on_event("shutdown")
async def shutdown():
    global _notification_task
    if _notification_task:
        _notification_task.cancel()
        try:
            await _notification_task
        except asyncio.CancelledError:
            pass
        _notification_task = None


@app.get("/health")
async def health_check():
    return {"status": "ok"}
