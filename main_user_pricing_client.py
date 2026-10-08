"""Read user-bot percentage adjustments from the shared pricing database."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PRICING_DB_PATH = "/home/kianirad2020/send_changes/pricing_settings.db"
DEFAULT_TRY_RATES_URL = "http://127.0.0.1:8000/api/rates/try"
MIN_ADJUSTMENT_PCT = Decimal("-50")
MAX_ADJUSTMENT_PCT = Decimal("50")
CANONICAL_TRY_SOURCE = "kiani-price-cache"
CANONICAL_TRY_ADJUSTMENTS = {
    "buy_lira": ("user_tl_buy_adjustment_pct", "buy_adjustment_pct"),
    "sell_lira": ("user_tl_sell_adjustment_pct", "sell_adjustment_pct"),
}
logger = logging.getLogger(__name__)


def pricing_db_path(override: str | None = None) -> str:
    return (
        override
        or os.getenv("KIANI_PRICING_DB_PATH")
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


def _read_required_adjustment_percentage(
    key: str,
    db_path: str | None = None,
) -> Decimal:
    """Read the exact admin-panel percentage; never substitute a default."""
    resolved_path = pricing_db_path(db_path)
    if not Path(resolved_path).is_file():
        raise RuntimeError("Shared TRY pricing database is unavailable")

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
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError("Could not read shared TRY pricing settings") from exc

    if not row:
        raise RuntimeError(f"Shared TRY pricing database is missing {key}")

    try:
        percentage = Decimal(str(row[0]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"Shared TRY pricing setting {key} is invalid") from exc
    if (
        not percentage.is_finite()
        or percentage < MIN_ADJUSTMENT_PCT
        or percentage > MAX_ADJUSTMENT_PCT
    ):
        raise RuntimeError(f"Shared TRY pricing setting {key} is out of range")
    return percentage


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
    db_path: str | None = None,
) -> int:
    """Fetch and verify a canonical TRY/Toman customer rate from the local Kiani API."""

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
    if not isinstance(rates, dict):
        raise RuntimeError("Canonical TRY API response is missing rate data")

    db_key, adjustment_key = CANONICAL_TRY_ADJUSTMENTS[rate_key]
    try:
        value = Decimal(str(rates[rate_key]))
        reported_adjustment = Decimal(str(rates[adjustment_key]))
        market_usdt_toman = Decimal(str(rates["market_usdt_toman"]))
        market_usdt_try = Decimal(str(rates["market_usdt_try"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Canonical TRY API response is missing pricing metadata or numeric rates"
        ) from exc

    if rates.get("source") != CANONICAL_TRY_SOURCE:
        raise RuntimeError("Canonical TRY API is not using the shared market source")
    if (
        not value.is_finite()
        or value <= 0
        or not reported_adjustment.is_finite()
        or reported_adjustment < MIN_ADJUSTMENT_PCT
        or reported_adjustment > MAX_ADJUSTMENT_PCT
        or not market_usdt_toman.is_finite()
        or market_usdt_toman <= 0
        or not market_usdt_try.is_finite()
        or market_usdt_try <= 0
    ):
        raise RuntimeError("Canonical TRY API returned invalid pricing metadata")

    configured_adjustment = _read_required_adjustment_percentage(db_key, db_path)
    if reported_adjustment != configured_adjustment:
        raise RuntimeError(
            "Canonical TRY API adjustment does not match the admin-panel setting"
        )

    expected_rate = (
        (market_usdt_toman / market_usdt_try)
        * (Decimal("1") + reported_adjustment / Decimal("100"))
        / Decimal("10")
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10")
    if value != expected_rate:
        raise RuntimeError(
            "Canonical TRY API rate does not match its market and adjustment metadata"
        )
    return int(value)


def calculate_canonical_try_rate_from_market(
    rate_key: str,
    usdt_irr: object,
    usdt_try: object,
    db_path: str | None = None,
) -> int:
    """Calculate one TRY/Toman quote from the bot's raw live market cache."""

    if rate_key not in CANONICAL_TRY_ADJUSTMENTS:
        raise ValueError(f"Unsupported canonical TRY rate: {rate_key}")

    try:
        irr_value = Decimal(str(usdt_irr))
        try_value = Decimal(str(usdt_try))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Live market cache returned non-numeric rates") from exc
    if (
        not irr_value.is_finite()
        or irr_value <= 0
        or not try_value.is_finite()
        or try_value <= 0
    ):
        raise ValueError("Live market cache returned invalid rates")

    db_key, _reported_key = CANONICAL_TRY_ADJUSTMENTS[rate_key]
    adjustment_pct = _read_required_adjustment_percentage(db_key, db_path)
    market_usdt_toman = irr_value / Decimal("10")
    factor = Decimal("1") + adjustment_pct / Decimal("100")
    rate = (
        (market_usdt_toman / try_value)
        * factor
        / Decimal("10")
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10")
    return int(rate)


async def get_canonical_try_rate_with_fallback(
    rate_key: str,
    price_cache: object,
    url: str | None = None,
    timeout: int = 15,
    db_path: str | None = None,
) -> int:
    """Prefer the canonical API; fall back to this bot's live market cache."""

    try:
        return await asyncio.to_thread(
            get_canonical_try_rate,
            rate_key,
            url,
            timeout,
            db_path,
        )
    except Exception as api_error:
        logger.warning(
            "Canonical TRY API failed; using bot live-cache fallback (%s)",
            type(api_error).__name__,
        )

    try:
        usdt_irr, usdt_try = await asyncio.gather(
            price_cache.get_usdt_irr(),
            price_cache.get_usdt_try(),
        )
        return await asyncio.to_thread(
            calculate_canonical_try_rate_from_market,
            rate_key,
            usdt_irr,
            usdt_try,
            db_path,
        )
    except Exception as fallback_error:
        logger.warning(
            "Bot live-cache TRY fallback failed (%s)",
            type(fallback_error).__name__,
        )
        raise RuntimeError(
            "Canonical TRY API and bot live-cache fallback both failed"
        ) from fallback_error
