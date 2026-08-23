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

# Older notification helpers may still read TELEGRAM_BOT_TOKEN. Keep the
# dedicated admin token mapping for compatibility without embedding any token.
admin_bot_token = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
if admin_bot_token:
    os.environ["TELEGRAM_BOT_TOKEN"] = admin_bot_token

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin_auth import validate_admin_config
from .auth import validate_auth_config
from .database import init_db
from .notification_watcher import notification_watcher
from .price_cache import price_cache
from .api import activity, admin, kyc, profile, rates, transactions, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    else:
        origins = [
            "https://miniapp.peerexo.com",
            "https://kianiapp.peerexo.com",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    if "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must not contain '*' in production")
    return origins


app = FastAPI(
    title="Exchange API",
    description="Backend API for the Telegram Mini App",
    version="1.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Register the hardened admin routes before legacy routers. Starlette resolves
# matching routes in registration order, so these bearer-authenticated routes
# take precedence over the older credential-in-query implementations that are
# kept temporarily for rollback compatibility.
app.include_router(admin.router, prefix="/api", tags=["admin"])
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
    validate_auth_config()
    validate_admin_config()
    init_db()
    profile.ensure_profile_schema()
    await price_cache.warm_cache()
    _notification_task = asyncio.create_task(notification_watcher())
    logger.info("Kiani API started with restricted CORS and bearer admin authentication")


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
    return {"status": "ok", "version": "1.4.0"}
