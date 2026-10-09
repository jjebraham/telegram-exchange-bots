"""Canonical TRY customer pricing calculated from the Kiani live rate cache.

The API supplies the same USDT/IRR and USDT/TRY values used by /rates/current.
This keeps the mini app, Telegram bot, and channel publisher on one price
snapshot without requiring a separate seven-exchange network fetch.
"""

from __future__ import annotations

import math
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_CHANNEL_SPLIT_DIR = Path(__file__).resolve().parents[3] / "channel_split"
CHANNEL_SPLIT_DIR = Path(
    os.environ.get("KIANI_CHANNEL_SPLIT_DIR", str(DEFAULT_CHANNEL_SPLIT_DIR))
).expanduser().resolve()

if str(CHANNEL_SPLIT_DIR) not in sys.path:
    sys.path.insert(0, str(CHANNEL_SPLIT_DIR))

from kiani_shared_pricing import (  # noqa: E402
    calculate_hawala_try_rate,
    calculate_kiani_try_rates,
    load_hawala_try_adjustment,
    load_try_adjustments,
)

CANONICAL_TRY_SOURCE = "kiani-price-cache"


def _positive_decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{label} must be positive and finite")
    return parsed


def _age_seconds(value: Any) -> float:
    try:
        age = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("market age is not numeric") from exc
    if not math.isfinite(age):
        raise ValueError("market age must be finite")
    return max(0.0, age)


def get_canonical_try_rates(
    market_usdt_toman: Decimal | int | float | str,
    market_usdt_try: Decimal | int | float | str,
    *,
    market_age_seconds: float = 0.0,
) -> dict[str, Any]:
    """Calculate the shared TRY/Toman customer quotes from the live API cache."""

    toman = _positive_decimal(market_usdt_toman, "market_usdt_toman")
    try_rate = _positive_decimal(market_usdt_try, "market_usdt_try")
    adjustments = load_try_adjustments()
    rates = calculate_kiani_try_rates(toman, try_rate, adjustments)

    return {
        "buy_lira": rates["buy_lira"],
        "sell_lira": rates["sell_lira"],
        "buy_adjustment_pct": adjustments["user_tl_buy_adjustment_pct"],
        "sell_adjustment_pct": adjustments["user_tl_sell_adjustment_pct"],
        "market_usdt_toman": toman,
        "market_usdt_try": try_rate,
        "source_count": 1,
        "market_age_seconds": _age_seconds(market_age_seconds),
    }


def get_canonical_hawala_try_rate(
    market_usdt_toman: Decimal | int | float | str,
    market_usdt_try: Decimal | int | float | str,
    *,
    market_age_seconds: float = 0.0,
) -> dict[str, Any]:
    """Calculate the Hawala TRY/Toman quote from the same live API cache."""

    toman = _positive_decimal(market_usdt_toman, "market_usdt_toman")
    try_rate = _positive_decimal(market_usdt_try, "market_usdt_try")
    adjustment_pct = load_hawala_try_adjustment()
    rate = calculate_hawala_try_rate(toman, try_rate, adjustment_pct)

    return {
        "hawala_try": rate,
        "adjustment_pct": adjustment_pct,
        "market_usdt_toman": toman,
        "market_usdt_try": try_rate,
        "source_count": 1,
        "market_age_seconds": _age_seconds(market_age_seconds),
    }
