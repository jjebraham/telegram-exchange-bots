#!/usr/bin/env python3
"""Direct Wallex public USDT/TMN market adapter for AlanChande."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from price_proxy import fetch_json_with_price_proxy

WALLEX_MARKETS_URL = "https://api.wallex.ir/hector/web/v1/markets"


@dataclass(frozen=True)
class WallexUsdtQuote:
    price_toman: Decimal
    change_24h_pct: Decimal
    is_spot: bool
    is_tmn_based: bool


def _decimal(value, field: str, *, allow_negative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Wallex field {field!r} is not numeric") from exc

    if not result.is_finite():
        raise ValueError(f"Wallex field {field!r} is not finite")
    if allow_negative:
        return result
    if result <= 0:
        raise ValueError(f"Wallex field {field!r} must be positive")
    return result


def parse_wallex_usdt_market(payload: dict) -> WallexUsdtQuote:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Wallex markets response was not successful")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Wallex markets response has no result object")

    markets = result.get("markets")
    if not isinstance(markets, list):
        raise ValueError("Wallex markets response has no markets list")

    market = next(
        (
            item for item in markets
            if isinstance(item, dict) and str(item.get("symbol", "")).upper() == "USDTTMN"
        ),
        None,
    )
    if market is None:
        raise ValueError("Wallex response has no USDTTMN market")

    quote = WallexUsdtQuote(
        price_toman=_decimal(market.get("price"), "price"),
        change_24h_pct=_decimal(
            market.get("change_24h", "0"),
            "change_24h",
            allow_negative=True,
        ),
        is_spot=bool(market.get("is_spot", False)),
        is_tmn_based=bool(market.get("is_tmn_based", False)),
    )

    if not quote.is_spot:
        raise ValueError("Wallex USDTTMN is not currently marked as a spot market")
    if not quote.is_tmn_based:
        raise ValueError("Wallex USDTTMN is not marked as TMN based")
    return quote


def fetch_wallex_usdt(timeout: float | None = None) -> WallexUsdtQuote:
    payload = fetch_json_with_price_proxy(
        WALLEX_MARKETS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
        timeout=timeout,
    )
    return parse_wallex_usdt_market(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    arrow = "🔼" if rounded > 0 else "🔻" if rounded < 0 else "⚪️"
    return f"{arrow} {abs(rounded):.2f}%".rstrip("0").rstrip(".")


def build_wallex_usdt_post(quote: WallexUsdtQuote) -> str:
    return "\n".join(
        [
            "💎 <b>تتر | والکس</b>",
            "",
            f"💰 <b>آخرین قیمت</b>　<code>{_fmt_toman(quote.price_toman)}</code> تومان",
            f"📊 <b>تغییر ۲۴ ساعت</b>　<code>{_fmt_pct(quote.change_24h_pct)}</code>",
            "",
            "ℹ️ این نرخ «آخرین قیمت بازار» است؛ نه بهترین سفارش خرید/فروش.",
        ]
    )
