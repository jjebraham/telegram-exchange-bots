#!/usr/bin/env python3
"""Direct Tabdeal USDT/IRT order-book adapter for AlanChande.

Official public endpoint:
GET https://api1.tabdeal.org/r/api/v1/depth?symbol=USDTIRT&limit=1

No API key is required for this market-data endpoint.
Tabdeal uses IRT for Toman-denominated markets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from price_proxy import fetch_json_with_price_proxy

TABDEAL_DEPTH_URL = "https://api1.tabdeal.org/r/api/v1/depth"


@dataclass(frozen=True)
class TabdealUsdtQuote:
    best_ask_toman: Decimal
    best_ask_quantity: Decimal
    best_bid_toman: Decimal
    best_bid_quantity: Decimal


def _positive_decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Tabdeal field {field!r} is not numeric") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError(f"Tabdeal field {field!r} must be positive")
    return result


def parse_tabdeal_usdt_depth(payload: dict) -> TabdealUsdtQuote:
    if not isinstance(payload, dict):
        raise ValueError("Tabdeal order-book response is not an object")

    bids = payload.get("bids")
    asks = payload.get("asks")

    if not isinstance(bids, list) or not bids:
        raise ValueError("Tabdeal response has no bids")
    if not isinstance(asks, list) or not asks:
        raise ValueError("Tabdeal response has no asks")

    best_bid = bids[0]
    best_ask = asks[0]

    if not isinstance(best_bid, list) or len(best_bid) < 2:
        raise ValueError("Tabdeal best bid row is malformed")
    if not isinstance(best_ask, list) or len(best_ask) < 2:
        raise ValueError("Tabdeal best ask row is malformed")

    quote = TabdealUsdtQuote(
        best_ask_toman=_positive_decimal(best_ask[0], "asks[0].price"),
        best_ask_quantity=_positive_decimal(best_ask[1], "asks[0].quantity"),
        best_bid_toman=_positive_decimal(best_bid[0], "bids[0].price"),
        best_bid_quantity=_positive_decimal(best_bid[1], "bids[0].quantity"),
    )

    if quote.best_bid_toman >= quote.best_ask_toman:
        raise ValueError("Tabdeal order book is crossed or invalid")

    return quote


def fetch_tabdeal_usdt(timeout: float | None = None) -> TabdealUsdtQuote:
    query = urlencode({"symbol": "USDTIRT", "limit": 1})
    payload = fetch_json_with_price_proxy(
        f"{TABDEAL_DEPTH_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
        timeout=timeout,
    )
    return parse_tabdeal_usdt_depth(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_qty(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def build_tabdeal_usdt_post(quote: TabdealUsdtQuote) -> str:
    spread = quote.best_ask_toman - quote.best_bid_toman
    return "\n".join(
        [
            "💎 <b>تتر | تبدیل</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_ask_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_bid_toman)}</code> تومان",
            "",
            f"📦 <b>حجم بهترین فروش</b>　<code>{_fmt_qty(quote.best_ask_quantity)}</code> USDT",
            f"📦 <b>حجم بهترین خرید</b>　<code>{_fmt_qty(quote.best_bid_quantity)}</code> USDT",
            f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
        ]
    )
