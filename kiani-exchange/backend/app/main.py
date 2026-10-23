import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .database import init_db
from .api import pricing, rates, users, transactions
from .price_cache import price_cache

# Preserve market module startup order while configuring the restored KYC routes.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from .api import kyc, kyc_admin
from .api import admin_portal

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
app.include_router(pricing.router, prefix="/api", tags=["pricing"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(transactions.router, prefix="/api", tags=["transactions"])
app.include_router(kyc.router, prefix="/api", tags=["kyc"])
app.include_router(kyc_admin.router, prefix="/api", tags=["kyc-admin"])
app.include_router(admin_portal.router, prefix='/api', tags=['admin-portal'])


@app.on_event("startup")
async def startup():
    init_db()
    kyc._ensure_schema()
    await price_cache.warm_cache()


@app.get("/health")
async def health_check():
    return {"status": "ok", "kyc": "enabled"}


# Precompute verified TRY rates outside incoming customer requests.
from .canonical_try_rates import start_canonical_try_background_refresh


@app.on_event("startup")
async def start_canonical_try_refresh_worker():
    start_canonical_try_background_refresh()


@app.on_event('startup')
async def initialize_sms_password_reset():
    from .password_reset import initialize
    initialize()
