from __future__ import annotations

import logging
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..admin_auth import optional_admin_session
from .users import _require_admin_access, _write_admin_log

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
    username: str | None = None
    password: str | None = None
    buy_adjustment_pct: str | float | int
    sell_adjustment_pct: str | float | int


class AdminRatesUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    user_tl_buy_adjustment_pct: str | float | int
    user_tl_sell_adjustment_pct: str | float | int


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


def _write_try_settings(buy: Decimal, sell: Decimal) -> None:
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
async def admin_get_try_pricing(
    username: str | None = None,
    password: str | None = None,
    session: dict[str, str] | None = Depends(optional_admin_session),
):
    role = _require_admin_access(
        session,
        {"admin", "support", "viewer"},
        username,
        password,
    )
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
async def admin_update_try_pricing(
    req: TryPricingUpdate,
    session: dict[str, str] | None = Depends(optional_admin_session),
):
    role = _require_admin_access(
        session,
        {"admin"},
        req.username,
        req.password,
    )
    buy = _parse_pct(req.buy_adjustment_pct, "buy_adjustment_pct")
    sell = _parse_pct(req.sell_adjustment_pct, "sell_adjustment_pct")
    _write_try_settings(buy, sell)

    actor = session["username"] if session else (req.username or "legacy-admin")
    logger.info(
        "TRY pricing updated by %s: buy=%s sell=%s",
        actor,
        buy,
        sell,
    )
    _write_admin_log(
        "update_try_pricing",
        {
            "username": actor,
            "role": role,
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


@router.get("/admin/rates")
async def admin_get_rates_compat(
    username: str | None = None,
    password: str | None = None,
    session: dict[str, str] | None = Depends(optional_admin_session),
):
    role = _require_admin_access(
        session,
        {"admin", "support", "viewer"},
        username,
        password,
    )
    values = _read_try_settings()
    return {
        "settings": {
            "user_tl_buy_adjustment_pct": float(
                values["user_tl_buy_adjustment_pct"]
            ),
            "user_tl_sell_adjustment_pct": float(
                values["user_tl_sell_adjustment_pct"]
            ),
        },
        "can_edit": role == "admin",
        "scope": "try_toman_only",
    }


@router.post("/admin/rates")
async def admin_update_rates_compat(
    req: AdminRatesUpdate,
    session: dict[str, str] | None = Depends(optional_admin_session),
):
    role = _require_admin_access(
        session,
        {"admin"},
        req.username,
        req.password,
    )
    buy = _parse_pct(
        req.user_tl_buy_adjustment_pct,
        "user_tl_buy_adjustment_pct",
    )
    sell = _parse_pct(
        req.user_tl_sell_adjustment_pct,
        "user_tl_sell_adjustment_pct",
    )
    _write_try_settings(buy, sell)

    actor = session["username"] if session else (req.username or "legacy-admin")
    _write_admin_log(
        "update_try_pricing",
        {
            "username": actor,
            "role": role,
            "user_tl_buy_adjustment_pct": str(buy),
            "user_tl_sell_adjustment_pct": str(sell),
            "source": "admin-rates-compat",
        },
    )
    return {
        "status": "success",
        "settings": {
            "user_tl_buy_adjustment_pct": float(buy),
            "user_tl_sell_adjustment_pct": float(sell),
        },
        "scope": "try_toman_only",
    }

