import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..price_cache import price_cache
from ..database import get_db
from ..exchange_math import derive_rates

router = APIRouter()

PAIR_KEYS = ["buy_lira", "sell_lira", "buy_usdt", "sell_usdt", "usdt_to_lira", "lira_to_usdt"]


class RatesAdjustmentRequest(BaseModel):
    username: str
    password: str
    adjustments: dict[str, float]


def _require_admin(username: str, password: str):
    admin_user = os.getenv("ADMIN_PANEL_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PANEL_PASSWORD", "admin123")
    if username != admin_user or password != admin_pass:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _load_adjustments() -> dict[str, float]:
    with get_db() as conn:
        rows = conn.execute("SELECT pair_key, percent FROM rate_adjustments").fetchall()
    found = {row["pair_key"]: float(row["percent"]) for row in rows}
    return {k: found.get(k, 0.0) for k in PAIR_KEYS}


def _apply_adjustments(base_rates: dict[str, float], adjustments: dict[str, float]) -> dict[str, float]:
    adjusted = {}
    for key, value in base_rates.items():
        factor = 1 + (adjustments.get(key, 0.0) / 100)
        if key in {"usdt_to_lira", "lira_to_usdt"}:
            adjusted[key] = round(value * factor, 2)
        else:
            adjusted[key] = round((value * factor) / 10) * 10
    return adjusted


@router.get("/rates/current")
async def get_current_rates():
    try:
        usdt_irr = await price_cache.get_usdt_irr()
        usdt_try = await price_cache.get_usdt_try()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch rates at this time",
        )

    base_rates = derive_rates(usdt_irr, usdt_try)
    adjustments = _load_adjustments()
    adjusted_rates = _apply_adjustments(base_rates, adjustments)

    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
        },
        "derived_rates": adjusted_rates,
        "rate_adjustments": adjustments,
    }


@router.get("/admin/rates/adjustments")
async def admin_get_rate_adjustments(username: str, password: str):
    _require_admin(username, password)
    return {"adjustments": _load_adjustments()}


@router.post("/admin/rates/adjustments")
async def admin_set_rate_adjustments(req: RatesAdjustmentRequest):
    _require_admin(req.username, req.password)

    with get_db() as conn:
        for key, value in req.adjustments.items():
            if key not in PAIR_KEYS:
                continue
            conn.execute(
                """INSERT INTO rate_adjustments(pair_key, percent, updated_at)
                   VALUES(?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(pair_key) DO UPDATE SET percent=excluded.percent, updated_at=CURRENT_TIMESTAMP""",
                (key, float(value)),
            )

    return {"status": "success", "adjustments": _load_adjustments()}
