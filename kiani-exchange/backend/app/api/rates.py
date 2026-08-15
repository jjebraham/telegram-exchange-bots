import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db
from ..exchange_math import derive_rates
from ..price_cache import price_cache

router = APIRouter()
logger = logging.getLogger(__name__)

RATE_SETTINGS_TABLE = "rate_settings_v2"

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


def _factor_to_percentage(value: object, fallback: float) -> float:
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return fallback
    return round((factor - 1.0) * 100.0, 6)


def _seed_from_legacy(conn) -> dict[str, float]:
    """Preserve the old single-row factor configuration when upgrading.

    Older deployments used a `rate_settings` table with one row containing
    factor columns. The new admin UI needs independent manual-rate and percentage
    values for six directions, so keep the old table untouched and translate its
    factors into percentages for the new v2 table on first use.
    """
    settings = dict(DEFAULT_SETTINGS)

    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rate_settings'"
    ).fetchone()
    if not table:
        return settings

    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(rate_settings)").fetchall()
    }
    legacy_columns = {
        "toman_to_tl_factor",
        "tl_to_toman_factor",
        "buy_usdt_factor",
        "sell_usdt_factor",
        "usdt_to_lira_factor",
        "lira_to_usdt_factor",
    }
    if not legacy_columns.issubset(columns):
        return settings

    row = conn.execute("SELECT * FROM rate_settings ORDER BY id LIMIT 1").fetchone()
    if not row:
        return settings

    settings["toman_to_tl_percentage"] = _factor_to_percentage(
        row["toman_to_tl_factor"], settings["toman_to_tl_percentage"]
    )
    settings["tl_to_toman_percentage"] = _factor_to_percentage(
        row["tl_to_toman_factor"], settings["tl_to_toman_percentage"]
    )
    settings["toman_to_usdt_percentage"] = _factor_to_percentage(
        row["buy_usdt_factor"], settings["toman_to_usdt_percentage"]
    )
    settings["usdt_to_toman_percentage"] = _factor_to_percentage(
        row["sell_usdt_factor"], settings["usdt_to_toman_percentage"]
    )
    settings["usdt_to_tl_percentage"] = _factor_to_percentage(
        row["usdt_to_lira_factor"], settings["usdt_to_tl_percentage"]
    )
    settings["tl_to_usdt_percentage"] = _factor_to_percentage(
        row["lira_to_usdt_factor"], settings["tl_to_usdt_percentage"]
    )

    logger.info("Seeded %s from legacy rate_settings factors", RATE_SETTINGS_TABLE)
    return settings


def _ensure_schema() -> None:
    with get_db() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {RATE_SETTINGS_TABLE} (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        count = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {RATE_SETTINGS_TABLE}"
        ).fetchone()["cnt"]
        if count == 0:
            seed = _seed_from_legacy(conn)
            for key, value in seed.items():
                conn.execute(
                    f"INSERT INTO {RATE_SETTINGS_TABLE} (key, value) VALUES (?, ?)",
                    (key, value),
                )
        else:
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    f"INSERT OR IGNORE INTO {RATE_SETTINGS_TABLE} (key, value) VALUES (?, ?)",
                    (key, value),
                )


def get_rate_settings() -> dict[str, float]:
    _ensure_schema()
    settings = dict(DEFAULT_SETTINGS)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT key, value FROM {RATE_SETTINGS_TABLE}"
        ).fetchall()
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


async def _admin_rate_snapshot(settings: dict[str, float]) -> dict:
    """Return market/effective rates when available without blocking admin settings.

    The admin must still be able to view and edit manual rates/percentages during a
    temporary upstream market-data outage. Public pricing continues to fail closed.
    """
    try:
        usdt_irr = await price_cache.get_usdt_irr()
        usdt_try = await price_cache.get_usdt_try()
        effective = derive_rates(usdt_irr, usdt_try, settings)
        return {
            "market_available": True,
            "market": {"USDT_IRR": usdt_irr, "USDT_TRY": usdt_try},
            "effective_rates": effective,
            "market_error": None,
        }
    except Exception as exc:
        logger.warning("Admin rate snapshot could not fetch market data: %s", exc)
        return {
            "market_available": False,
            "market": {},
            "effective_rates": {},
            "market_error": "upstream_market_data_unavailable",
        }


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
    settings = get_rate_settings()
    snapshot = await _admin_rate_snapshot(settings)
    return {
        "settings": settings,
        **snapshot,
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
                f"""INSERT INTO {RATE_SETTINGS_TABLE} (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
                (key, float(value)),
            )
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("rate_settings_updated", "12 pair rate/percentage settings updated"),
        )

    settings = get_rate_settings()
    snapshot = await _admin_rate_snapshot(settings)
    return {
        "status": "success",
        "settings": settings,
        **snapshot,
    }
