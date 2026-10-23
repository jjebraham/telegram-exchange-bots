"""Canonical Toman↔TRY pricing shared by channel, bot, and mini-app.

The market base deliberately reuses the exact channel source stack:
- median customer-buy USDT/Toman quote from the verified hybrid exchange set
- BTCTurk USDT/TRY last price

Only the market snapshot is cached briefly. Customer-facing percentages are read
from pricing_settings.db on every request so panel changes take effect immediately.
"""

from __future__ import annotations

import logging
import math
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
from .shahidi_rate_client import fetch_shahidi_snapshot  # noqa: E402

logger = logging.getLogger(__name__)
MAX_STALE_SECONDS = 90
PRIMARY_TRY_SOURCE = "channel-hybrid-usdt+btcturk"
FALLBACK_TRY_SOURCE = "shahidi-market"


class CanonicalTrySnapshotUnavailable(RuntimeError):
    """No validated market snapshot exists inside the safe age limit."""

_CACHE_LOCK = threading.Lock()
_MARKET_CACHE: dict[str, Any] | None = None
_REFRESH_LOCK = threading.Lock()
_REFRESH_START_LOCK = threading.Lock()
_REFRESH_THREAD: threading.Thread | None = None



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
    if _kiani_akamai_module().enabled():
        return _akamai_market_snapshot(allow_refresh=True, force_refresh=force_refresh, max_cache_age=_ttl_seconds())[0]
    global _MARKET_CACHE

    ttl = _ttl_seconds()

    # A fresh cached result must never wait for external network calls.
    with _CACHE_LOCK:
        current = dict(_MARKET_CACHE) if _MARKET_CACHE else None
        if (
            not force_refresh
            and current is not None
            and time.monotonic() - current["fetched_monotonic"] <= ttl
        ):
            return current

    # Only one thread performs a slow market refresh.
    # Do not hold _CACHE_LOCK during network operations.
    with _REFRESH_LOCK:
        with _CACHE_LOCK:
            current = dict(_MARKET_CACHE) if _MARKET_CACHE else None
            if (
                not force_refresh
                and current is not None
                and time.monotonic() - current["fetched_monotonic"] <= ttl
            ):
                return current

        snapshot = collect_hybrid_usdt_snapshot()
        market_usdt_toman = _median_buy_toman(snapshot.quotes)
        market_usdt_try = fetch_btcturk_usdt_try()

        updated = {
            "market_usdt_toman": market_usdt_toman,
            "market_usdt_try": market_usdt_try,
            "source_count": len(snapshot.quotes),
            "source": PRIMARY_TRY_SOURCE,
            "fetched_monotonic": time.monotonic(),
        }

        with _CACHE_LOCK:
            _MARKET_CACHE = updated

        return dict(updated)


def _cached_market_snapshot() -> tuple[dict[str, Any], float]:
    if _kiani_akamai_module().enabled():
        return _akamai_market_snapshot(allow_refresh=False)
    with _CACHE_LOCK:
        market = dict(_MARKET_CACHE) if _MARKET_CACHE else None

    if market is None:
        raise CanonicalTrySnapshotUnavailable(
            "Canonical TRY snapshot not initialized"
        )

    try:
        age = time.monotonic() - float(market["fetched_monotonic"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CanonicalTrySnapshotUnavailable(
            "Canonical TRY snapshot metadata is invalid"
        ) from exc

    if not math.isfinite(age) or age < 0 or age > MAX_STALE_SECONDS:
        raise CanonicalTrySnapshotUnavailable(
            "Canonical TRY snapshot is outside the safe age limit"
        )
    return market, max(0.0, age)


def _try_rates_from_snapshot(
    market: dict[str, Any],
    age: float,
) -> dict[str, Any]:
    if _kiani_akamai_module().enabled():
        _kiani_akamai_module().read_validated_feed()
        if market.get("akamai_feed") is not True or market.get("source") != PRIMARY_TRY_SOURCE:
            raise CanonicalTrySnapshotUnavailable("Legacy market snapshot is not executable in Akamai mode")
    market_usdt_toman = Decimal(str(market["market_usdt_toman"]))
    market_usdt_try = Decimal(str(market["market_usdt_try"]))
    if (
        not market_usdt_toman.is_finite()
        or market_usdt_toman <= 0
        or not market_usdt_try.is_finite()
        or market_usdt_try <= 0
    ):
        raise ValueError("Canonical TRY market values must be finite and positive")

    source_count = int(market["source_count"])
    market_source = str(market.get("source", PRIMARY_TRY_SOURCE))
    minimum_sources = (_kiani_akamai_module().ORDER_MINIMUM_SOURCES
                       if _kiani_akamai_module().enabled() else 5)
    valid_primary = market_source == PRIMARY_TRY_SOURCE and minimum_sources <= source_count <= 7
    valid_fallback = market_source == FALLBACK_TRY_SOURCE and source_count == 1
    if not (valid_primary or valid_fallback):
        raise ValueError("Canonical TRY market source or quorum is invalid")

    adjustments = load_try_adjustments()
    rates = calculate_kiani_try_rates(
        market_usdt_toman,
        market_usdt_try,
        adjustments,
    )
    buy_lira = Decimal(str(rates["buy_lira"]))
    sell_lira = Decimal(str(rates["sell_lira"]))
    if (
        not buy_lira.is_finite()
        or buy_lira <= 0
        or not sell_lira.is_finite()
        or sell_lira <= 0
        or buy_lira < sell_lira
    ):
        raise ValueError("Canonical TRY customer rates are invalid or crossed")

    return {
        "buy_lira": rates["buy_lira"],
        "sell_lira": rates["sell_lira"],
        "buy_adjustment_pct": adjustments["user_tl_buy_adjustment_pct"],
        "sell_adjustment_pct": adjustments["user_tl_sell_adjustment_pct"],
        "market_usdt_toman": market_usdt_toman,
        "market_usdt_try": market_usdt_try,
        "source_count": source_count,
        "market_age_seconds": age,
        "market_stale": age > _ttl_seconds(),
        "source": market_source,
    }


def _shahidi_market_snapshot() -> tuple[dict[str, Any], float]:
    # Use Shahidi raw inputs only when the service reports a safe market age.
    if _kiani_akamai_module().enabled():
        raise CanonicalTrySnapshotUnavailable("Single-source fallback is disabled in Akamai mode")
    try:
        _customer_rates, raw = fetch_shahidi_snapshot(timeout=6)
        age = Decimal(str(raw["market_age_seconds"]))
        usdt_irr = Decimal(str(raw["USDT_IRR"]))
        usdt_try = Decimal(str(raw["USDT_TRY"]))
    except Exception as exc:
        raise CanonicalTrySnapshotUnavailable(
            f"Fresh Shahidi market fallback unavailable ({type(exc).__name__})"
        ) from exc
    if (
        not age.is_finite() or age < 0 or age > MAX_STALE_SECONDS
        or not usdt_irr.is_finite() or usdt_irr <= 0
        or not usdt_try.is_finite() or usdt_try <= 0
    ):
        raise CanonicalTrySnapshotUnavailable(
            "Shahidi market fallback is invalid or older than the safe age limit"
        )
    age_seconds = float(age)
    return ({
        "market_usdt_toman": usdt_irr / Decimal("10"),
        "market_usdt_try": usdt_try,
        "source_count": 1,
        "source": FALLBACK_TRY_SOURCE,
        "fetched_monotonic": time.monotonic() - age_seconds,
    }, age_seconds)


def _market_for_quote(*, force_refresh: bool = False) -> tuple[dict[str, Any], float]:
    if _kiani_akamai_module().enabled():
        return _akamai_market_snapshot(allow_refresh=force_refresh, force_refresh=force_refresh)
    if force_refresh:
        market = _fresh_market_snapshot(force_refresh=True)
        return market, max(
            0.0,
            time.monotonic() - float(market["fetched_monotonic"]),
        )
    try:
        return _cached_market_snapshot()
    except CanonicalTrySnapshotUnavailable:
        # Never queue a user request behind the multi-provider refresh lock.
        return _shahidi_market_snapshot()


def get_cached_canonical_try_rates() -> dict[str, Any]:
    """Return fresh or bounded-age validated rates without external I/O."""

    market, age = _cached_market_snapshot()
    return _try_rates_from_snapshot(market, age)


def _background_canonical_try_refresh() -> None:
    while True:
        try:
            _fresh_market_snapshot(force_refresh=True)
        except Exception as exc:
            logger.warning(
                "Canonical TRY refresh failed: %s: %s",
                type(exc).__name__,
                exc,
            )

        time.sleep(max(5, min(30, _ttl_seconds() // 2)))


def start_canonical_try_background_refresh() -> None:
    global _REFRESH_THREAD

    with _REFRESH_START_LOCK:
        if _REFRESH_THREAD is not None and _REFRESH_THREAD.is_alive():
            return

        _REFRESH_THREAD = threading.Thread(
            target=_background_canonical_try_refresh,
            daemon=True,
            name="kiani-canonical-try-refresh",
        )
        _REFRESH_THREAD.start()


def get_canonical_try_rates(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return the canonical pair from a snapshot no more than 90 seconds old.

    Direction semantics:
    - buy_lira: customer buys TRY from us (Toman -> TRY)
    - sell_lira: customer sells TRY to us (TRY -> Toman)
    """

    market, age = _market_for_quote(force_refresh=force_refresh)
    return _try_rates_from_snapshot(market, age)


def get_canonical_hawala_try_rate(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return Hawala payout from the shared market snapshot and its own setting."""

    market, age = _market_for_quote(force_refresh=force_refresh)
    adjustment_pct = load_hawala_try_adjustment()
    market_usdt_toman = Decimal(str(market["market_usdt_toman"]))
    market_usdt_try = Decimal(str(market["market_usdt_try"]))
    rate = calculate_hawala_try_rate(
        market_usdt_toman,
        market_usdt_try,
        adjustment_pct,
    )
    if not rate.is_finite() or rate <= 0:
        raise ValueError("Canonical Hawala TRY rate must be finite and positive")

    return {
        "hawala_try": rate,
        "adjustment_pct": adjustment_pct,
        "market_usdt_toman": market_usdt_toman,
        "market_usdt_try": market_usdt_try,
        "source_count": int(market["source_count"]),
        "market_age_seconds": age,
        "market_stale": age > _ttl_seconds(),
        "source": str(market.get("source", PRIMARY_TRY_SOURCE)),
    }


# Kiani Akamai cutover v2: shared runtime flag, no credentials or network I/O.
def _kiani_akamai_module():
    import sys
    from pathlib import Path
    folder = Path(__file__).resolve().parents[3] / "channel_split"
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    import akamai_rate_feed
    return akamai_rate_feed


def _akamai_market_snapshot(*, allow_refresh, force_refresh=False, max_cache_age=MAX_STALE_SECONDS):
    global _MARKET_CACHE
    feed_module = _kiani_akamai_module()
    feed = feed_module.read_validated_feed()

    def cached():
        with _CACHE_LOCK:
            value = dict(_MARKET_CACHE) if _MARKET_CACHE else None
        if value is None or value.get("akamai_feed") is not True:
            return None
        age = time.monotonic() - float(value["fetched_monotonic"])
        if not math.isfinite(age) or not 0 <= age <= max_cache_age:
            return None
        return value

    market = cached()
    if force_refresh or market is None:
        if not allow_refresh:
            raise CanonicalTrySnapshotUnavailable("Akamai-backed BTCTurk snapshot unavailable")
        with _REFRESH_LOCK:
            market = cached()
            if force_refresh or market is None:
                # Preserve the upstream ticker proof when caching the Akamai conversion.
                from akamai_btcturk import fetch_btcturk_snapshot
                btcturk = fetch_btcturk_snapshot()
                usdt_try = btcturk["price"]
                if not usdt_try.is_finite() or usdt_try <= 0:
                    raise CanonicalTrySnapshotUnavailable("Invalid BTCTurk value")
                market = {"market_usdt_try": usdt_try, "source": PRIMARY_TRY_SOURCE,
                          "akamai_feed": True, "fetched_monotonic": time.monotonic() -
                          max(0.0, time.time() - btcturk["proof_epoch"])}
                with _CACHE_LOCK:
                    _MARKET_CACHE = dict(market)
    # Revalidate after any network wait; source age is never reset on cache reads.
    feed = feed_module.read_validated_feed()
    age = max(feed["age_seconds"], time.monotonic()-float(market["fetched_monotonic"]))
    if not math.isfinite(age) or not 0 <= age <= MAX_STALE_SECONDS:
        raise CanonicalTrySnapshotUnavailable("Akamai/BTCTurk snapshot expired")
    result = dict(market, market_usdt_toman=feed["median_buy_toman"],
                  source_count=feed["source_count"], source=PRIMARY_TRY_SOURCE)
    return result, age
