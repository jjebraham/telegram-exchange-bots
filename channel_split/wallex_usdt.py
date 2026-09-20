#!/usr/bin/env python3
"""Direct Wallex USDT/TMN market adapter for AlanChande.

This intentionally follows the active Kiani backend pattern:
- public Wallex /v1/markets endpoint;
- optional WALLEX_API_KEY header;
- outbound requests through the shared PRICE_PROXY_* pool.

For USDTTMN:
- askPrice = lowest sell order -> price a user pays to buy USDT;
- bidPrice = highest buy order -> price a user receives when selling USDT.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from price_proxy import fetch_json_with_price_proxy

DEFAULT_WALLEX_BASE_URL = "https://api.wallex.ir/v1"


@dataclass(frozen=True)
class WallexUsdtQuote:
    best_ask_toman: Decimal
    best_bid_toman: Decimal
    last_toman: Decimal
    change_24h_pct: Decimal
    high_24h_toman: Decimal
    low_24h_toman: Decimal


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

    symbols = result.get("symbols")
    if not isinstance(symbols, dict):
        raise ValueError("Wallex markets response has no symbols object")

    market = symbols.get("USDTTMN")
    if not isinstance(market, dict):
        raise ValueError("Wallex response has no USDTTMN market")

    stats = market.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("Wallex USDTTMN market has no stats object")

    return WallexUsdtQuote(
        best_ask_toman=_decimal(stats.get("askPrice"), "askPrice"),
        best_bid_toman=_decimal(stats.get("bidPrice"), "bidPrice"),
        last_toman=_decimal(stats.get("lastPrice"), "lastPrice"),
        change_24h_pct=_decimal(
            stats.get("24h_ch", "0"),
            "24h_ch",
            allow_negative=True,
        ),
        high_24h_toman=_decimal(stats.get("24h_highPrice"), "24h_highPrice"),
        low_24h_toman=_decimal(stats.get("24h_lowPrice"), "24h_lowPrice"),
    )


def fetch_wallex_usdt(timeout: float | None = None) -> WallexUsdtQuote:
    base_url = os.getenv("WALLEX_BASE_URL", DEFAULT_WALLEX_BASE_URL).strip().rstrip("/")
    if not base_url:
        base_url = DEFAULT_WALLEX_BASE_URL

    headers = {
        "Accept": "application/json",
        "User-Agent": "AlanChande-DirectMarket/1.0",
    }
    api_key = os.getenv("WALLEX_API_KEY", "").strip()
    if api_key:
        headers["X-API-KEY"] = api_key

    payload = fetch_json_with_price_proxy(
        f"{base_url}/markets",
        headers=headers,
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
    spread = quote.best_ask_toman - quote.best_bid_toman
    return "\n".join(
        [
            "💎 <b>تتر | والکس</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_ask_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_bid_toman)}</code> تومان",
            "",
            f"🔹 <b>آخرین معامله</b>　<code>{_fmt_toman(quote.last_toman)}</code>",
            f"📈 <b>سقف ۲۴ ساعت</b>　<code>{_fmt_toman(quote.high_24h_toman)}</code>",
            f"📉 <b>کف ۲۴ ساعت</b>　<code>{_fmt_toman(quote.low_24h_toman)}</code>",
            f"📊 <b>تغییر ۲۴ ساعت</b>　<code>{_fmt_pct(quote.change_24h_pct)}</code>",
            f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
        ]
    )
