import asyncio
import math
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException

from ..canonical_try_rates import (
    CANONICAL_TRY_SOURCE,
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
    """Preserve the miniapp's existing non-TRY rate calculation."""

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


async def _market_snapshot() -> dict[str, object]:
    """Read both market inputs through the price cache used by /rates/current."""

    try:
        usdt_irr, usdt_try = await asyncio.gather(
            price_cache.get_usdt_irr(),
            price_cache.get_usdt_try(),
        )
        irr_value = Decimal(str(usdt_irr))
        try_value = Decimal(str(usdt_try))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch rates at this time",
        ) from exc

    if (
        not irr_value.is_finite()
        or irr_value <= 0
        or not try_value.is_finite()
        or try_value <= 0
    ):
        raise HTTPException(
            status_code=503,
            detail="Rate source returned invalid market values",
        )

    now = time.time()
    timestamps: list[float] = []
    for name in ("usdt_irr_time", "usdt_try_time"):
        try:
            timestamp = float(getattr(price_cache, name, 0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp) and timestamp > 0:
            timestamps.append(timestamp)
    age = max(0.0, now - min(timestamps)) if timestamps else 0.0

    return {
        "usdt_irr": usdt_irr,
        "usdt_try": usdt_try,
        "market_usdt_toman": irr_value / Decimal("10"),
        "market_usdt_try": try_value,
        "market_age_seconds": age,
    }


def _try_payload(snapshot: dict[str, object]) -> dict[str, object]:
    result = get_canonical_try_rates(
        snapshot["market_usdt_toman"],
        snapshot["market_usdt_try"],
        market_age_seconds=snapshot["market_age_seconds"],
    )
    return {
        "buy_lira": int(result["buy_lira"]),
        "sell_lira": int(result["sell_lira"]),
        "buy_adjustment_pct": str(result["buy_adjustment_pct"]),
        "sell_adjustment_pct": str(result["sell_adjustment_pct"]),
        "market_usdt_toman": str(result["market_usdt_toman"]),
        "market_usdt_try": str(result["market_usdt_try"]),
        "source_count": result["source_count"],
        "market_age_seconds": round(float(result["market_age_seconds"]), 3),
        "source": CANONICAL_TRY_SOURCE,
    }


def _hawala_payload(snapshot: dict[str, object]) -> dict[str, object]:
    result = get_canonical_hawala_try_rate(
        snapshot["market_usdt_toman"],
        snapshot["market_usdt_try"],
        market_age_seconds=snapshot["market_age_seconds"],
    )
    return {
        "hawala_try": int(result["hawala_try"]),
        "adjustment_pct": str(result["adjustment_pct"]),
        "market_usdt_toman": str(result["market_usdt_toman"]),
        "market_usdt_try": str(result["market_usdt_try"]),
        "source_count": result["source_count"],
        "market_age_seconds": round(float(result["market_age_seconds"]), 3),
        "source": CANONICAL_TRY_SOURCE,
    }


async def _canonical_try_payload(
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot = snapshot or await _market_snapshot()
    try:
        return await asyncio.to_thread(_try_payload, snapshot)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to calculate canonical TRY rates: {type(exc).__name__}",
        ) from exc


async def _canonical_hawala_try_payload(
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot = snapshot or await _market_snapshot()
    try:
        return await asyncio.to_thread(_hawala_payload, snapshot)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to calculate canonical Hawala TRY rate: {type(exc).__name__}",
        ) from exc


@router.get("/rates/try")
async def get_try_rates():
    """Canonical Toman↔TRY pair from the live Kiani price cache."""

    return {"rates": await _canonical_try_payload()}


@router.get("/rates/hawala-try")
async def get_hawala_try_rate():
    """Canonical Hawala TRY/Toman payout from the same market cache."""

    return {"rates": await _canonical_hawala_try_payload()}


@router.get("/rates/current")
async def get_current_rates():
    snapshot = await _market_snapshot()
    canonical_try = await _canonical_try_payload(snapshot)
    compatibility = _legacy_non_try_rates(
        snapshot["usdt_irr"],
        snapshot["usdt_try"],
    )
    rates = {
        "USDT_IRR": snapshot["usdt_irr"],
        "USDT_TRY": snapshot["usdt_try"],
        # These fields are shared by the existing miniapp bundle.
        "buy_lira": canonical_try["buy_lira"],
        "sell_lira": canonical_try["sell_lira"],
        **compatibility,
        "TRY_BUY_TOMAN": canonical_try["buy_lira"],
        "TRY_SELL_TOMAN": canonical_try["sell_lira"],
        "TRY_BUY_ADJUSTMENT_PCT": canonical_try["buy_adjustment_pct"],
        "TRY_SELL_ADJUSTMENT_PCT": canonical_try["sell_adjustment_pct"],
        "TRY_RATE_SOURCE": canonical_try["source"],
    }

    # Hawala is a separate product; its missing adjustment must not take down
    # the customer rate response used by the miniapp and Telegram buttons.
    try:
        hawala = await _canonical_hawala_try_payload(snapshot)
    except HTTPException:
        pass
    else:
        rates.update({
            "HAWALA_TRY_TOMAN": hawala["hawala_try"],
            "HAWALA_TRY_ADJUSTMENT_PCT": hawala["adjustment_pct"],
            "HAWALA_TRY_RATE_SOURCE": hawala["source"],
        })

    return {"rates": rates}
