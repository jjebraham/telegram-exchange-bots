import logging

from fastapi import APIRouter, HTTPException

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


def _factor_to_percentage(value: object, fallback: float) -> float:
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return fallback
    return round((factor - 1.0) * 100.0, 6)


def _seed_from_legacy(conn) -> dict[str, float]:
    """Preserve the old single-row factor configuration when upgrading."""
    settings = dict(DEFAULT_SETTINGS)
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rate_settings'"
    ).fetchone()
    if not table:
        return settings

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(rate_settings)").fetchall()}
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

    settings["toman_to_tl_percentage"] = _factor_to_percentage(row["toman_to_tl_factor"], settings["toman_to_tl_percentage"])
    settings["tl_to_toman_percentage"] = _factor_to_percentage(row["tl_to_toman_factor"], settings["tl_to_toman_percentage"])
    settings["toman_to_usdt_percentage"] = _factor_to_percentage(row["buy_usdt_factor"], settings["toman_to_usdt_percentage"])
    settings["usdt_to_toman_percentage"] = _factor_to_percentage(row["sell_usdt_factor"], settings["usdt_to_toman_percentage"])
    settings["usdt_to_tl_percentage"] = _factor_to_percentage(row["usdt_to_lira_factor"], settings["usdt_to_tl_percentage"])
    settings["tl_to_usdt_percentage"] = _factor_to_percentage(row["lira_to_usdt_factor"], settings["tl_to_usdt_percentage"])
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
        count = conn.execute(f"SELECT COUNT(*) AS cnt FROM {RATE_SETTINGS_TABLE}").fetchone()["cnt"]
        if count == 0:
            seed = _seed_from_legacy(conn)
            for key, value in seed.items():
                conn.execute(f"INSERT INTO {RATE_SETTINGS_TABLE} (key, value) VALUES (?, ?)", (key, value))
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
        rows = conn.execute(f"SELECT key, value FROM {RATE_SETTINGS_TABLE}").fetchall()
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
    """Return market/effective rates without blocking admin settings on outage."""
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
        "rates": {"USDT_IRR": usdt_irr, "USDT_TRY": usdt_try, **effective},
        "settings": settings,
    }
