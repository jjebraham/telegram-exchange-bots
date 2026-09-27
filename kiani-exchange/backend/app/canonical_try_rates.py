"""Canonical Toman↔TRY pricing shared by channel, bot, and mini-app.

The market base deliberately reuses the exact channel source stack:
- median customer-buy USDT/Toman quote from the verified hybrid exchange set
- BTCTurk USDT/TRY last price

Only the market snapshot is cached briefly. Customer-facing percentages are read
from pricing_settings.db on every request so panel changes take effect immediately.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_CHANNEL_SPLIT_DIR = Path(__file__).resolve().parents[3] / "channel_split"
CHANNEL_SPLIT_DIR = Path(
    os.environ.get("KIANI_CHANNEL_SPLIT_DIR", str(DEFAULT_CHANNEL_SPLIT_DIR))
).expanduser().resolve()

if str(CHANNEL_SPLIT_DIR) not in sys.path:
    sys.path.insert(0, str(CHANNEL_SPLIT_DIR))

from hybrid_usdt_compare import collect_hybrid_usdt_snapshot  # noqa: E402
from kiani_shared_pricing import (  # noqa: E402
    calculate_hawala_try_rate,
    calculate_kiani_try_rates,
    fetch_btcturk_usdt_try,
    load_hawala_try_adjustment,
    load_try_adjustments,
)

_CACHE_LOCK = threading.Lock()
_MARKET_CACHE: dict[str, Any] | None = None


def _ttl_seconds() -> int:
    raw = os.environ.get("KIANI_TRY_MARKET_TTL_SECONDS", "60")
    try:
        value = int(raw)
    except ValueError:
        value = 60
    return min(max(value, 5), 300)


def _median_buy_toman(quotes: list[Any]) -> Decimal:
    values = sorted(Decimal(str(quote.buy_toman)) for quote in quotes)
    if not values:
        raise RuntimeError("No verified USDT/Toman market values for Kiani TRY pricing")
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / Decimal("2")


def _fresh_market_snapshot(*, force_refresh: bool = False) -> dict[str, Any]:
    global _MARKET_CACHE

    ttl = _ttl_seconds()
    with _CACHE_LOCK:
        now = time.monotonic()
        if (
            not force_refresh
            and _MARKET_CACHE is not None
            and now - float(_MARKET_CACHE["fetched_monotonic"]) <= ttl
        ):
            return dict(_MARKET_CACHE)

        snapshot = collect_hybrid_usdt_snapshot()
        market_usdt_toman = _median_buy_toman(snapshot.quotes)
        market_usdt_try = fetch_btcturk_usdt_try()

        _MARKET_CACHE = {
            "market_usdt_toman": market_usdt_toman,
            "market_usdt_try": market_usdt_try,
            "source_count": len(snapshot.quotes),
            "fetched_monotonic": time.monotonic(),
        }
        return dict(_MARKET_CACHE)


def get_canonical_try_rates(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return one canonical Toman↔TRY quote pair.

    Direction semantics:
    - buy_lira: customer buys TRY from us (Toman -> TRY)
    - sell_lira: customer sells TRY to us (TRY -> Toman)
    """

    market = _fresh_market_snapshot(force_refresh=force_refresh)
    adjustments = load_try_adjustments()
    rates = calculate_kiani_try_rates(
        market["market_usdt_toman"],
        market["market_usdt_try"],
        adjustments,
    )

    return {
        "buy_lira": rates["buy_lira"],
        "sell_lira": rates["sell_lira"],
        "buy_adjustment_pct": adjustments["user_tl_buy_adjustment_pct"],
        "sell_adjustment_pct": adjustments["user_tl_sell_adjustment_pct"],
        "market_usdt_toman": market["market_usdt_toman"],
        "market_usdt_try": market["market_usdt_try"],
        "source_count": int(market["source_count"]),
        "market_age_seconds": max(
            0.0,
            time.monotonic() - float(market["fetched_monotonic"]),
        ),
    }


def get_canonical_hawala_try_rate(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return the Hawala TRY/Toman payout using the canonical market base.

    This intentionally keeps the Hawala business adjustment independent from the
    interactive/channel sell adjustment. When both percentages are equal, all
    surfaces produce the exact same TRY/Toman quote.
    """

    market = _fresh_market_snapshot(force_refresh=force_refresh)
    adjustment_pct = load_hawala_try_adjustment()
    rate = calculate_hawala_try_rate(
        market["market_usdt_toman"],
        market["market_usdt_try"],
        adjustment_pct,
    )

    return {
        "hawala_try": rate,
        "adjustment_pct": adjustment_pct,
        "market_usdt_toman": market["market_usdt_toman"],
        "market_usdt_try": market["market_usdt_try"],
        "source_count": int(market["source_count"]),
        "market_age_seconds": max(
            0.0,
            time.monotonic() - float(market["fetched_monotonic"]),
        ),
    }
