import logging
import os
from dotenv import load_dotenv

# Load environment variables before importing modules that read them at import time.
load_dotenv()

# This backend uses the admin bot for registration/login/transaction notifications.
# Keep TELEGRAM_BOT_TOKEN available for the user-facing bot, but map the dedicated
# admin token into the legacy variable expected by existing backend modules.
admin_bot_token = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
if admin_bot_token:
    os.environ["TELEGRAM_BOT_TOKEN"] = admin_bot_token

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .api import rates, users, transactions
from .price_cache import price_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Kiani Exchange API",
    description="Backend API for Kiani Exchange Telegram Mini App",
    version="1.0.0",
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


@app.on_event("startup")
async def startup():
    init_db()
    await price_cache.warm_cache()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
