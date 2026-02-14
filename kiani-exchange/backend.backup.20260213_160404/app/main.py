import logging
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from .database import init_db
from .api import rates, users, transactions
from .price_cache import price_cache

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Get the base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_BUILD_DIR = os.path.join(BASE_DIR, "..", "frontend", "mini-app", "dist")

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

# Serve static files from the frontend build directory (must be after API routes)
if os.path.exists(FRONTEND_BUILD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_BUILD_DIR, "assets")), name="assets")
    
    # Serve index.html for all other routes (for SPA) - must be last
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Don't interfere with API routes
        if full_path.startswith("api/"):
            return None
        # Serve index.html for all other routes
        index_path = os.path.join(FRONTEND_BUILD_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}
else:
    logging.warning(f"Frontend build directory not found: {FRONTEND_BUILD_DIR}")
