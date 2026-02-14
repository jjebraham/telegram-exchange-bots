import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .security import RateLimitMiddleware, SecurityHeadersMiddleware
from .database import init_db
from .api import admin_plan, rates, transactions, users
from .api.admin_security import router as admin_security_router
from .price_cache import price_cache

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)
logging.info(f"Loaded environment from: {env_path}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Kiani Exchange API",
    description="Backend API for Kiani Exchange Telegram Mini App",
    version="1.0.0",
)

allowed_origins = [origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "https://kianiapp.peerexo.com").split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Captcha-Token", "X-User-Id", "X-Failed-Attempts"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(rates.router, prefix="/api", tags=["rates"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(transactions.router, prefix="/api", tags=["transactions"])
app.include_router(admin_plan.router, prefix="/api", tags=["admin-plan"])
app.include_router(admin_security_router, prefix="/api")


@app.on_event("startup")
async def startup():
    init_db()
    await price_cache.warm_cache()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
