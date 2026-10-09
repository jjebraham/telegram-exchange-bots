"""Read user-bot percentage adjustments from the shared pricing database."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
import time
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


def _read_required_adjustment_percentages(
    keys: tuple[str, ...],
    db_path: str | None = None,
) -> dict[str, Decimal]:
    """Read a consistent set of admin-panel percentages without defaults."""

    resolved_path = pricing_db_path(db_path)
    if not Path(resolved_path).is_file():
        raise RuntimeError("Shared TRY pricing database is unavailable")

    try:
        connection = sqlite3.connect(resolved_path, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout = 3000")
            placeholders = ",".join("?" for _ in keys)
            rows = connection.execute(
                f"SELECT key, value FROM pricing_settings WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError("Could not read shared TRY pricing settings") from exc

    found = {str(key): raw_value for key, raw_value in rows}
    missing = [key for key in keys if key not in found]
    if missing:
        raise RuntimeError(
            "Shared TRY pricing database is missing " + ", ".join(missing)
        )

    percentages: dict[str, Decimal] = {}
    for key in keys:
        try:
            percentage = Decimal(str(found[key]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError(f"Shared TRY pricing setting {key} is invalid") from exc
        if (
            not percentage.is_finite()
            or percentage < MIN_ADJUSTMENT_PCT
            or percentage > MAX_ADJUSTMENT_PCT
        ):
            raise RuntimeError(f"Shared TRY pricing setting {key} is out of range")
        percentages[key] = percentage
    return percentages


def _read_required_adjustment_percentage(
    key: str,
    db_path: str | None = None,
) -> Decimal:
    return _read_required_adjustment_percentages((key,), db_path)[key]


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



def _calculate_rate(
    market_usdt_toman: Decimal,
    market_usdt_try: Decimal,
    adjustment_pct: Decimal,
) -> int:
    rate = (
        (market_usdt_toman / market_usdt_try)
        * (Decimal("1") + adjustment_pct / Decimal("100"))
        / Decimal("10")
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10")
    return int(rate)


def get_canonical_try_rates(
    url: str | None = None,
    timeout: int = 15,
    db_path: str | None = None,
) -> dict[str, int]:
    """Fetch, validate, and return both directions from one canonical API call."""

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
    if rates.get("source") != CANONICAL_TRY_SOURCE:
        raise RuntimeError("Canonical TRY API is not using the shared market source")

    try:
        market_usdt_toman = Decimal(str(rates["market_usdt_toman"]))
        market_usdt_try = Decimal(str(rates["market_usdt_try"]))
        reported = {
            rate_key: Decimal(str(rates[reported_key]))
            for rate_key, (_db_key, reported_key) in CANONICAL_TRY_ADJUSTMENTS.items()
        }
        values = {
            rate_key: Decimal(str(rates[rate_key]))
            for rate_key in CANONICAL_TRY_ADJUSTMENTS
        }
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Canonical TRY API response is missing pricing metadata or numeric rates"
        ) from exc

    if (
        not market_usdt_toman.is_finite()
        or market_usdt_toman <= 0
        or not market_usdt_try.is_finite()
        or market_usdt_try <= 0
    ):
        raise RuntimeError("Canonical TRY API returned invalid market values")

    configured_adjustments = _read_required_adjustment_percentages(
        tuple(db_key for db_key, _reported_key in CANONICAL_TRY_ADJUSTMENTS.values()),
        db_path,
    )
    validated: dict[str, int] = {}
    for rate_key, (db_key, _reported_key) in CANONICAL_TRY_ADJUSTMENTS.items():
        value = values[rate_key]
        reported_adjustment = reported[rate_key]
        if (
            not value.is_finite()
            or value <= 0
            or not reported_adjustment.is_finite()
            or reported_adjustment < MIN_ADJUSTMENT_PCT
            or reported_adjustment > MAX_ADJUSTMENT_PCT
        ):
            raise RuntimeError("Canonical TRY API returned invalid pricing metadata")

        configured_adjustment = configured_adjustments[db_key]
        if reported_adjustment != configured_adjustment:
            raise RuntimeError(
                "Canonical TRY API adjustment does not match the admin-panel setting"
            )

        expected_rate = _calculate_rate(
            market_usdt_toman,
            market_usdt_try,
            reported_adjustment,
        )
        if value != expected_rate:
            raise RuntimeError(
                "Canonical TRY API rate does not match its market and adjustment metadata"
            )
        validated[rate_key] = int(value)

    return validated


def get_canonical_try_rate(
    rate_key: str,
    url: str | None = None,
    timeout: int = 15,
    db_path: str | None = None,
) -> int:
    """Fetch and verify one rate from the shared canonical quote pair."""

    if rate_key not in CANONICAL_TRY_ADJUSTMENTS:
        raise ValueError(f"Unsupported canonical TRY rate: {rate_key}")
    return get_canonical_try_rates(url, timeout, db_path)[rate_key]


def calculate_canonical_try_rates_from_market(
    usdt_irr: object,
    usdt_try: object,
    db_path: str | None = None,
) -> dict[str, int]:
    """Calculate both TRY/Toman directions from the bot's live market cache."""

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

    market_usdt_toman = irr_value / Decimal("10")
    configured_adjustments = _read_required_adjustment_percentages(
        tuple(db_key for db_key, _reported_key in CANONICAL_TRY_ADJUSTMENTS.values()),
        db_path,
    )
    result: dict[str, int] = {}
    for rate_key, (db_key, _reported_key) in CANONICAL_TRY_ADJUSTMENTS.items():
        adjustment_pct = configured_adjustments[db_key]
        result[rate_key] = _calculate_rate(
            market_usdt_toman,
            try_value,
            adjustment_pct,
        )
    return result


def calculate_canonical_try_rate_from_market(
    rate_key: str,
    usdt_irr: object,
    usdt_try: object,
    db_path: str | None = None,
) -> int:
    """Calculate one TRY/Toman quote from the bot's raw live market cache."""

    if rate_key not in CANONICAL_TRY_ADJUSTMENTS:
        raise ValueError(f"Unsupported canonical TRY rate: {rate_key}")
    return calculate_canonical_try_rates_from_market(
        usdt_irr,
        usdt_try,
        db_path,
    )[rate_key]


RATE_CACHE_TTL_SECONDS = 300
_RATE_CACHE_LOCK = asyncio.Lock()
RATE_CACHE_TABLE = "kiani_try_rate_cache"


def _try_rate_cache_db_path() -> Path:
    configured = os.getenv("KIANI_TRY_RATE_CACHE_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "kiani-exchange" / "try-rates.sqlite3"


def _ensure_rate_cache_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RATE_CACHE_TABLE} (
            cache_key TEXT PRIMARY KEY,
            buy_lira INTEGER NOT NULL,
            sell_lira INTEGER NOT NULL,
            cached_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )


def _read_cached_try_rates(db_path: Path, now: float | None = None) -> dict[str, int] | None:
    if not db_path.is_file():
        return None

    try:
        with sqlite3.connect(db_path, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout = 30000")
            _ensure_rate_cache_table(connection)
            row = connection.execute(
                f"SELECT buy_lira, sell_lira, expires_at FROM {RATE_CACHE_TABLE} "
                "WHERE cache_key = ?",
                ("customer",),
            ).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError("Could not read the persistent TRY rate cache") from exc

    if row is None:
        return None
    try:
        buy_lira, sell_lira = int(row[0]), int(row[1])
        expires_at = float(row[2])
    except (TypeError, ValueError, OverflowError):
        return None
    current_time = time.time() if now is None else now
    if (
        buy_lira <= 0
        or sell_lira <= 0
        or not math.isfinite(expires_at)
        or expires_at <= current_time
    ):
        return None
    return {"buy_lira": buy_lira, "sell_lira": sell_lira}


def _store_cached_try_rates(
    rates: dict[str, int],
    db_path: Path,
    now: float | None = None,
) -> None:
    current_time = time.time() if now is None else now
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(db_path, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout = 30000")
            _ensure_rate_cache_table(connection)
            connection.execute(
                f"""
                INSERT INTO {RATE_CACHE_TABLE}
                    (cache_key, buy_lira, sell_lira, cached_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    buy_lira = excluded.buy_lira,
                    sell_lira = excluded.sell_lira,
                    cached_at = excluded.cached_at,
                    expires_at = excluded.expires_at
                """,
                (
                    "customer",
                    rates["buy_lira"],
                    rates["sell_lira"],
                    current_time,
                    current_time + RATE_CACHE_TTL_SECONDS,
                ),
            )
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError("Could not save the persistent TRY rate cache") from exc


async def get_canonical_try_rate_with_fallback(
    rate_key: str,
    price_cache: object,
    url: str | None = None,
    timeout: int = 15,
    db_path: str | None = None,
) -> int:
    """Serve the shared five-minute pair cache; refresh it once when expired."""

    if rate_key not in CANONICAL_TRY_ADJUSTMENTS:
        raise ValueError(f"Unsupported canonical TRY rate: {rate_key}")

    cache_db = _try_rate_cache_db_path()
    cached = await asyncio.to_thread(_read_cached_try_rates, cache_db)
    if cached is not None:
        return cached[rate_key]

    async with _RATE_CACHE_LOCK:
        # Another request may have refreshed the cache while this one waited.
        cached = await asyncio.to_thread(_read_cached_try_rates, cache_db)
        if cached is not None:
            return cached[rate_key]

        try:
            rates = await asyncio.to_thread(
                get_canonical_try_rates,
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
                rates = await asyncio.to_thread(
                    calculate_canonical_try_rates_from_market,
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

        await asyncio.to_thread(_store_cached_try_rates, rates, cache_db)
        return rates[rate_key]
