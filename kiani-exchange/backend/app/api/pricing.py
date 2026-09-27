from __future__ import annotations

import logging
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .users import _require_roles, _write_admin_log

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_PRICING_DB = Path("/home/kianirad2020/send_changes/pricing_settings.db")
TRY_KEYS = (
    "user_tl_buy_adjustment_pct",
    "user_tl_sell_adjustment_pct",
)
MIN_PCT = Decimal("-50")
MAX_PCT = Decimal("50")


class TryPricingUpdate(BaseModel):
    username: str
    password: str
    buy_adjustment_pct: str | float | int
    sell_adjustment_pct: str | float | int


def _pricing_db_path() -> Path:
    return Path(
        os.environ.get("KIANI_PRICING_DB_PATH", str(DEFAULT_PRICING_DB))
    ).expanduser()


def _parse_pct(value: object, key: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid_{key}") from exc
    if not parsed.is_finite() or parsed < MIN_PCT or parsed > MAX_PCT:
        raise HTTPException(status_code=400, detail=f"{key}_out_of_range")
    return parsed


def _read_try_settings() -> dict[str, Decimal]:
    path = _pricing_db_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="pricing_db_missing")
    try:
        with sqlite3.connect(path, timeout=3) as connection:
            connection.execute("PRAGMA busy_timeout = 3000")
            rows = connection.execute(
                "SELECT key, value FROM pricing_settings WHERE key IN (?, ?)",
                TRY_KEYS,
            ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="pricing_db_unavailable") from exc

    values: dict[str, Decimal] = {}
    for key, value in rows:
        values[str(key)] = _parse_pct(value, str(key))
    missing = [key for key in TRY_KEYS if key not in values]
    if missing:
        raise HTTPException(
            status_code=503,
            detail="missing_pricing_settings:" + ",".join(missing),
        )
    return values


@router.get("/admin/pricing/try")
async def admin_get_try_pricing(username: str, password: str):
    role = _require_roles(username, password, {"admin", "support", "viewer"})
    values = _read_try_settings()
    return {
        "pricing": {
            "buy_lira": {
                "key": "user_tl_buy_adjustment_pct",
                "direction": "Toman -> TRY",
                "label_fa": "خرید لیر از ما",
                "adjustment_pct": str(values["user_tl_buy_adjustment_pct"]),
            },
            "sell_lira": {
                "key": "user_tl_sell_adjustment_pct",
                "direction": "TRY -> Toman",
                "label_fa": "فروش لیر به ما",
                "adjustment_pct": str(values["user_tl_sell_adjustment_pct"]),
            },
        },
        "can_edit": role == "admin",
    }


@router.post("/admin/pricing/try")
async def admin_update_try_pricing(req: TryPricingUpdate):
    _require_roles(req.username, req.password, {"admin"})
    buy = _parse_pct(req.buy_adjustment_pct, "buy_adjustment_pct")
    sell = _parse_pct(req.sell_adjustment_pct, "sell_adjustment_pct")

    path = _pricing_db_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="pricing_db_missing")

    try:
        with sqlite3.connect(path, timeout=3) as connection:
            connection.execute("PRAGMA busy_timeout = 3000")
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT key FROM pricing_settings WHERE key IN (?, ?)",
                    TRY_KEYS,
                ).fetchall()
            }
            missing = [key for key in TRY_KEYS if key not in existing]
            if missing:
                raise HTTPException(
                    status_code=503,
                    detail="missing_pricing_settings:" + ",".join(missing),
                )
            connection.execute(
                "UPDATE pricing_settings SET value = ? WHERE key = ?",
                (str(buy), "user_tl_buy_adjustment_pct"),
            )
            connection.execute(
                "UPDATE pricing_settings SET value = ? WHERE key = ?",
                (str(sell), "user_tl_sell_adjustment_pct"),
            )
            connection.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="pricing_db_unavailable") from exc

    logger.info(
        "TRY pricing updated by %s: buy=%s sell=%s",
        req.username,
        buy,
        sell,
    )
    _write_admin_log(
        "update_try_pricing",
        {
            "username": req.username,
            "user_tl_buy_adjustment_pct": str(buy),
            "user_tl_sell_adjustment_pct": str(sell),
        },
    )

    return {
        "status": "success",
        "pricing": {
            "buy_adjustment_pct": str(buy),
            "sell_adjustment_pct": str(sell),
        },
    }
