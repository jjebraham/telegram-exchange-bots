import asyncio
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException

from ..canonical_try_rates import get_canonical_try_rates
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


async def _canonical_try_payload():
    try:
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
        "source": "channel-hybrid-usdt+btcturk",
    }


@router.get("/rates/try")
async def get_try_rates():
    """Canonical Toman↔TRY pair used by all Kiani surfaces."""

    return {"rates": await _canonical_try_payload()}


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

    canonical_try = await _canonical_try_payload()
    compatibility = _legacy_non_try_rates(usdt_irr, usdt_try)
    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
            # Backward-compatible fields consumed by the currently deployed
            # miniapp bundle. Keep these identical to the canonical TRY pair.
            "buy_lira": canonical_try["buy_lira"],
            "sell_lira": canonical_try["sell_lira"],
            **compatibility,
            "TRY_BUY_TOMAN": canonical_try["buy_lira"],
            "TRY_SELL_TOMAN": canonical_try["sell_lira"],
            "TRY_BUY_ADJUSTMENT_PCT": canonical_try["buy_adjustment_pct"],
            "TRY_SELL_ADJUSTMENT_PCT": canonical_try["sell_adjustment_pct"],
            "TRY_RATE_SOURCE": canonical_try["source"],
        }
    }
