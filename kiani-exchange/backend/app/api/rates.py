import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db
from ..exchange_math import derive_rates
from ..price_cache import price_cache

router = APIRouter()

DEFAULT_SETTINGS: dict[str, float] = {
    "toman_to_tl_manual_rate": 0.0,
    "toman_to_tl_percentage": -0.5,
    "tl_to_toman_manual_rate": 0.0,
    "tl_to_toman_percentage": -6.0,
    "tl_to_usdt_manual_rate": 0.0,
    "tl_to_usdt_percentage": 2.0,
    "usdt_to_tl_manual_rate": 0.0,
    "usdt_to_tl_percentage": -2.0,
    "toman_to_usdt_manual_rate": 0.0,
    "toman_to_usdt_percentage": 1.0,
    "usdt_to_toman_manual_rate": 0.0,
    "usdt_to_toman_percentage": -1.0,
}


class AdminRateSettings(BaseModel):
    username: str
    password: str
    toman_to_tl_manual_rate: float = 0.0
    toman_to_tl_percentage: float = -0.5
    tl_to_toman_manual_rate: float = 0.0
    tl_to_toman_percentage: float = -6.0
    tl_to_usdt_manual_rate: float = 0.0
    tl_to_usdt_percentage: float = 2.0
    usdt_to_tl_manual_rate: float = 0.0
    usdt_to_tl_percentage: float = -2.0
    toman_to_usdt_manual_rate: float = 0.0
    toman_to_usdt_percentage: float = 1.0
    usdt_to_toman_manual_rate: float = 0.0
    usdt_to_toman_percentage: float = -1.0


def _require_admin(username: str, password: str) -> None:
    configured_user = os.getenv("ADMIN_PANEL_USERNAME", "").strip()
    configured_password = os.getenv("ADMIN_PANEL_PASSWORD", "")
    if not configured_user or not configured_password:
        raise HTTPException(status_code=503, detail="admin_credentials_not_configured")
    if username != configured_user or password != configured_password:
        raise HTTPException(status_code=401, detail="unauthorized")


def _ensure_schema() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_settings (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO rate_settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def get_rate_settings() -> dict[str, float]:
    _ensure_schema()
    settings = dict(DEFAULT_SETTINGS)
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM rate_settings").fetchall()
    for row in rows:
        if row["key"] in settings:
            settings[row["key"]] = float(row["value"])
    return settings


async def get_effective_rates() -> tuple[dict[str, float], dict[str, float], float, float]:
    try:
        usdt_irr = await price_cache.get_usdt_irr()
        usdt_try = await price_cache.get_usdt_try()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to fetch rates at this time") from exc

    settings = get_rate_settings()
    effective = derive_rates(usdt_irr, usdt_try, settings)
    return effective, settings, usdt_irr, usdt_try


@router.get("/rates/current")
async def get_current_rates():
    effective, settings, usdt_irr, usdt_try = await get_effective_rates()
    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
            **effective,
        },
        "settings": settings,
    }


@router.get("/admin/rates")
async def admin_get_rates(username: str, password: str):
    _require_admin(username, password)
    effective, settings, usdt_irr, usdt_try = await get_effective_rates()
    return {
        "settings": settings,
        "effective_rates": effective,
        "market": {"USDT_IRR": usdt_irr, "USDT_TRY": usdt_try},
    }


@router.post("/admin/rates")
async def admin_update_rates(req: AdminRateSettings):
    _require_admin(req.username, req.password)
    values = req.model_dump(exclude={"username", "password"})

    for key, value in values.items():
        numeric = float(value)
        if key.endswith("_percentage") and not (-50.0 <= numeric <= 50.0):
            raise HTTPException(status_code=400, detail=f"invalid_percentage:{key}")
        if key.endswith("_manual_rate") and numeric < 0:
            raise HTTPException(status_code=400, detail=f"invalid_manual_rate:{key}")

    _ensure_schema()
    with get_db() as conn:
        for key, value in values.items():
            conn.execute(
                """INSERT INTO rate_settings (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
                (key, float(value)),
            )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("rate_settings_updated", "12 pair rate/percentage settings updated"),
        )

    effective, settings, usdt_irr, usdt_try = await get_effective_rates()
    return {
        "status": "success",
        "settings": settings,
        "effective_rates": effective,
        "market": {"USDT_IRR": usdt_irr, "USDT_TRY": usdt_try},
    }
