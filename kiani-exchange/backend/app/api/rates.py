import asyncio

from fastapi import APIRouter, HTTPException

from ..canonical_try_rates import get_canonical_try_rates
from ..price_cache import price_cache

router = APIRouter()


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
    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
            "TRY_BUY_TOMAN": canonical_try["buy_lira"],
            "TRY_SELL_TOMAN": canonical_try["sell_lira"],
            "TRY_BUY_ADJUSTMENT_PCT": canonical_try["buy_adjustment_pct"],
            "TRY_SELL_ADJUSTMENT_PCT": canonical_try["sell_adjustment_pct"],
            "TRY_RATE_SOURCE": canonical_try["source"],
        }
    }
