"""Read and validate the admin-adjusted canonical Kiani TRY customer quote."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CANONICAL_TRY_RATES_URL = "https://miniapp.kiani.exchange/api/rates/try"
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


def _decimal(value: Any, key: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Canonical TRY field {key!r} is not numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"Canonical TRY field {key!r} must be finite")
    return parsed


def parse_canonical_try_rates(payload: Any) -> dict[str, Decimal]:
    """Validate the canonical endpoint response and return its adjusted pair."""
    raw = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("Canonical TRY response does not contain a rates object")

    required = (
        "buy_lira",
        "sell_lira",
        "buy_adjustment_pct",
        "sell_adjustment_pct",
        "source_count",
        "market_age_seconds",
        "market_stale",
        "source",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError("Canonical TRY response is missing: " + ", ".join(missing))

    buy = _decimal(raw["buy_lira"], "buy_lira")
    sell = _decimal(raw["sell_lira"], "sell_lira")
    buy_adjustment = _decimal(raw["buy_adjustment_pct"], "buy_adjustment_pct")
    sell_adjustment = _decimal(raw["sell_adjustment_pct"], "sell_adjustment_pct")
    age = _decimal(raw["market_age_seconds"], "market_age_seconds")
    source_count = raw["source_count"]

    if buy <= 0 or sell <= 0 or buy < sell:
        raise ValueError("Canonical TRY customer rates are invalid or crossed")
    if buy != buy.to_integral_value() or sell != sell.to_integral_value():
        raise ValueError("Canonical TRY customer rates must be whole toman")
    if abs(buy_adjustment) > 50 or abs(sell_adjustment) > 50:
        raise ValueError("Canonical TRY adjustment is outside the supported range")
    if age < 0 or age > 90 or raw["market_stale"] is not False:
        raise ValueError("Canonical TRY market data is stale or outside the safe age")
    if (
        isinstance(source_count, bool)
        or not isinstance(source_count, int)
        or not 1 <= source_count <= 7
    ):
        raise ValueError("Canonical TRY source count is invalid")
    if not isinstance(raw["source"], str) or not raw["source"].strip():
        raise ValueError("Canonical TRY source metadata is invalid")

    return {"buy_lira": buy, "sell_lira": sell}


def merge_canonical_try_rates(
    other_rates: dict[str, Decimal],
    canonical_rates: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Keep other assets as-is while requiring canonical buy/sell TRY values."""
    missing = [
        key for key in ("buy_lira", "sell_lira")
        if key not in canonical_rates
    ]
    if missing:
        raise ValueError("Canonical TRY rates are missing: " + ", ".join(missing))
    return {**other_rates, **canonical_rates}


def fetch_canonical_try_rates(
    url: str | None = None,
    *,
    timeout: float = 8,
    attempts: int = 3,
    retry_delay: float = 1,
) -> dict[str, Decimal]:
    """Fetch the adjusted canonical TRY pair; never fall back to /rates/current."""
    target = (url or os.getenv("KIANI_TRY_RATES_URL", DEFAULT_CANONICAL_TRY_RATES_URL)).strip()
    if not target:
        raise ValueError("Canonical TRY rates URL is empty")

    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        request = Request(
            target,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": "KianiCanonicalTryRateClient/1.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(65_537)
            if len(body) > 65_536:
                raise ValueError("Canonical TRY response is too large")
            return parse_canonical_try_rates(json.loads(body))
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"Canonical TRY API returned HTTP {exc.code}: {detail}"
            )
            retryable = exc.code in TRANSIENT_HTTP_CODES
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = RuntimeError(f"Could not load canonical TRY rates: {exc}")
            retryable = True
        except ValueError:
            raise

        if not retryable or attempt >= max(1, attempts):
            assert last_error is not None
            raise last_error
        time.sleep(max(0, retry_delay))

    assert last_error is not None
    raise last_error

