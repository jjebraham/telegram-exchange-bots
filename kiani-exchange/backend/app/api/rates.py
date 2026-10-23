import asyncio
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException

from ..shahidi_rate_client import fetch_shahidi_snapshot, miniapp_rate_payload

from ..canonical_try_rates import (
    CanonicalTrySnapshotUnavailable,
    get_cached_canonical_try_rates,
    get_canonical_hawala_try_rate,
    get_canonical_try_rates,
)
from ..price_cache import price_cache

router = APIRouter()


def _round_10(value: Decimal) -> int:
    # Match the restored miniapp's positive-number Math.round(... / 10) * 10.
    return int((value / Decimal("10")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ) * Decimal("10"))


def _legacy_non_try_rates(usdt_irr: object, usdt_try: object) -> dict[str, float | int]:
    """Preserve the restored miniapp's non-TRY display math exactly.

    Only buy_lira/sell_lira are replaced by the canonical channel calculation.
    These compatibility fields prevent the restored bundle from turning the
    unrelated USDT/cross rates into NaN when it detects server-side TRY rates.
    """

    toman = Decimal(str(usdt_irr)) / Decimal("10")
    market_try = Decimal(str(usdt_try))
    return {
        "buy_usdt": _round_10(toman * Decimal("1.01")),
        "sell_usdt": _round_10(toman * Decimal("0.99")),
        "usdt_to_lira": float(
            (market_try * Decimal("0.98")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        ),
        "lira_to_usdt": float(
            (market_try * Decimal("1.02")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        ),
        "foreign_payment": _round_10(toman * Decimal("1.05")),
    }


async def _canonical_hawala_try_payload():
    try:
        result = await asyncio.to_thread(get_canonical_hawala_try_rate)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to fetch canonical Hawala TRY rate: {type(exc).__name__}",
        ) from exc

    return {
        "hawala_try": int(result["hawala_try"]),
        "adjustment_pct": str(result["adjustment_pct"]),
        "market_usdt_toman": str(result["market_usdt_toman"]),
        "market_usdt_try": str(result["market_usdt_try"]),
        "source_count": result["source_count"],
        "market_age_seconds": round(float(result["market_age_seconds"]), 3),
        "market_stale": bool(result.get("market_stale", False)),
        "source": result.get("source", "channel-hybrid-usdt+btcturk"),
    }


async def _canonical_try_payload():
    try:
        try:
            result = await asyncio.to_thread(get_cached_canonical_try_rates)
        except CanonicalTrySnapshotUnavailable:
            # A cold process gets one bounded, single-flight market refresh.
            result = await asyncio.to_thread(get_canonical_try_rates)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to fetch canonical TRY rates: {type(exc).__name__}",
        ) from exc

    return {
        "buy_lira": int(result["buy_lira"]),
        "sell_lira": int(result["sell_lira"]),
        "buy_adjustment_pct": str(result["buy_adjustment_pct"]),
        "sell_adjustment_pct": str(result["sell_adjustment_pct"]),
        "market_usdt_toman": str(result["market_usdt_toman"]),
        "market_usdt_try": str(result["market_usdt_try"]),
        "source_count": result["source_count"],
        "market_age_seconds": round(float(result["market_age_seconds"]), 3),
        "market_stale": bool(result.get("market_stale", False)),
        "source": result.get("source", "channel-hybrid-usdt+btcturk"),
    }


@router.get("/rates/try")
async def get_try_rates():
    """Canonical Toman↔TRY pair used by all Kiani surfaces."""

    return {"rates": await _canonical_try_payload()}


@router.get("/rates/hawala-try")
async def get_hawala_try_rate():
    """Canonical Hawala TRY/Toman payout using the shared Hawala adjustment."""

    return {"rates": await _canonical_hawala_try_payload()}


@router.get("/rates/current")
async def get_current_rates():
    """Return Shahidi's final customer rates for display and order estimates."""
    try:
        rates, raw_market = await asyncio.to_thread(fetch_shahidi_snapshot)
    except Exception as primary_error:
        try:
            rates, raw_market = await asyncio.to_thread(_fetch_akamai_display_snapshot)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Customer rates are temporarily unavailable",
            ) from exc
        payload = {
            key: (int(value) if key in ('buy_lira', 'sell_lira', 'buy_usdt', 'sell_usdt', 'foreign_payment')
                  else float(value)) if value is not None else None
            for key, value in rates.items()
        }
        payload.update({key: raw_market.get(key) for key in (
            'USDT_IRR', 'USDT_TRY', 'market_source', 'market_source_count',
            'market_age_seconds', 'market_feed_valid_until_utc', 'market_status', 'display_confidence')})
        payload.update(TRY_BUY_TOMAN=payload['buy_lira'], TRY_SELL_TOMAN=payload['sell_lira'], RATE_SOURCE='shahidi.site')
        for key in ("rate_mode", "transaction_rates_available", "minimum_sources",
                    "market_source_providers", "market_usdt_try_age_seconds"):
            payload[key] = raw_market[key]
        payload.update(trading_minimum_sources=2, display_minimum_sources=1, source_agreement_max_deviation_pct=2)
        return {"rates": payload}
    return {"rates": miniapp_rate_payload(rates, raw_market)}


def _fetch_akamai_display_snapshot():
    """Local display-only path; orders require two fresh agreeing sources."""
    import json
    from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
    from ..canonical_try_rates import _kiani_akamai_module
    module = _kiani_akamai_module()
    module.read_display_feed()

    class RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = Request("http://127.0.0.1:8003/api/rates/display",
                      headers={"Accept":"application/json","Cache-Control":"no-cache"})
    opener = build_opener(ProxyHandler({}), RejectRedirects())
    with opener.open(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("Display upstream did not return 200")
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Display response is too large")
    payload = json.loads(body)
    raw = payload["rates"]
    module.validate_display_market(raw)
    keys = ('buy_lira', 'sell_lira', 'buy_usdt', 'sell_usdt',
            'lira_to_usdt', 'usdt_to_lira', 'foreign_payment')
    rates = {key: Decimal(str(raw[key])) if raw[key] is not None else None for key in keys}
    return rates, raw
