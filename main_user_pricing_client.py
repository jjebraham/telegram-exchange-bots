"""Read user-bot percentage adjustments from the shared pricing database."""

from __future__ import annotations

import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PRICING_DB_PATH = "/home/kianirad2020/send_changes/pricing_settings.db"
DEFAULT_TRY_RATES_URL = "http://127.0.0.1:8000/api/rates/try"
MIN_ADJUSTMENT_PCT = Decimal("-50")
MAX_ADJUSTMENT_PCT = Decimal("50")


def pricing_db_path(override: str | None = None) -> str:
    return (
        override
        or os.getenv("PRICING_DB_PATH")
        or DEFAULT_PRICING_DB_PATH
    )


def _parse_percentage(value: object, default: Decimal) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default

    if not parsed.is_finite():
        return default
    if parsed < MIN_ADJUSTMENT_PCT or parsed > MAX_ADJUSTMENT_PCT:
        return default
    return parsed


def get_adjustment_percentage(
    key: str,
    default_percentage: Decimal | str,
    db_path: str | None = None,
) -> Decimal:
    """Return a valid percentage, falling back without interrupting the bot."""

    default = _parse_percentage(default_percentage, Decimal("0"))
    resolved_path = pricing_db_path(db_path)

    if not Path(resolved_path).is_file():
        return default

    try:
        connection = sqlite3.connect(resolved_path, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout = 3000")
            row = connection.execute(
                "SELECT value FROM pricing_settings WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return default

    if not row:
        return default
    return _parse_percentage(row[0], default)


def get_adjustment_factor(
    key: str,
    default_percentage: Decimal | str,
    db_path: str | None = None,
) -> Decimal:
    percentage = get_adjustment_percentage(
        key,
        default_percentage,
        db_path,
    )
    return Decimal("1") + (percentage / Decimal("100"))


def get_canonical_try_rate(
    rate_key: str,
    url: str | None = None,
    timeout: int = 15,
) -> int:
    """Fetch one canonical TRY/Toman customer rate from the local Kiani API."""

    if rate_key not in {"buy_lira", "sell_lira"}:
        raise ValueError(f"Unsupported canonical TRY rate: {rate_key}")

    endpoint = (
        url
        or os.getenv("KIANI_TRY_RATES_URL")
        or DEFAULT_TRY_RATES_URL
    )
    request = Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "User-Agent": "Kiani-MainUserBot/2.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Canonical TRY API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Canonical TRY API unavailable: {exc}") from exc

    rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(rates, dict) or rate_key not in rates:
        raise RuntimeError("Canonical TRY API response is missing rate data")

    try:
        value = Decimal(str(rates[rate_key]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("Canonical TRY API returned a non-numeric rate") from exc

    if not value.is_finite() or value <= 0:
        raise RuntimeError("Canonical TRY API returned an invalid rate")
    return int(value)
