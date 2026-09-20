#!/usr/bin/env python3
"""Direct Exir USDT/IRT order-book adapter for AlanChande.

Official public endpoint:
GET https://api.exir.io/v2/orderbook?symbol=usdt-irt

No API key is required for public market data.
Exir's current consumer site labels USDT/IRT as the Toman market.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from price_proxy import fetch_json_direct_then_price_proxy

EXIR_ORDERBOOK_URL = "https://api.exir.io/v2/orderbook"
EXIR_SYMBOL = "usdt-irt"


@dataclass(frozen=True)
class ExirUsdtQuote:
    best_ask_toman: Decimal
    best_ask_quantity: Decimal
    best_bid_toman: Decimal
    best_bid_quantity: Decimal
    source_timestamp: str | None


def _positive_decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Exir field {field!r} is not numeric") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError(f"Exir field {field!r} must be positive")
    return result


def parse_exir_usdt_orderbook(payload: dict) -> ExirUsdtQuote:
    if not isinstance(payload, dict):
        raise ValueError("Exir order-book response is not an object")

    market = payload.get(EXIR_SYMBOL)
    if not isinstance(market, dict):
        raise ValueError(f"Exir response has no {EXIR_SYMBOL} market")

    bids = market.get("bids")
    asks = market.get("asks")

    if not isinstance(bids, list) or not bids:
        raise ValueError("Exir response has no bids")
    if not isinstance(asks, list) or not asks:
        raise ValueError("Exir response has no asks")

    best_bid = bids[0]
    best_ask = asks[0]

    if not isinstance(best_bid, list) or len(best_bid) < 2:
        raise ValueError("Exir best bid row is malformed")
    if not isinstance(best_ask, list) or len(best_ask) < 2:
        raise ValueError("Exir best ask row is malformed")

    quote = ExirUsdtQuote(
        best_ask_toman=_positive_decimal(best_ask[0], "asks[0].price"),
        best_ask_quantity=_positive_decimal(best_ask[1], "asks[0].quantity"),
        best_bid_toman=_positive_decimal(best_bid[0], "bids[0].price"),
        best_bid_quantity=_positive_decimal(best_bid[1], "bids[0].quantity"),
        source_timestamp=(
            str(market.get("timestamp")).strip()
            if market.get("timestamp") is not None
            else None
        ),
    )

    if quote.best_bid_toman >= quote.best_ask_toman:
        raise ValueError("Exir order book is crossed or invalid")

    return quote


def fetch_exir_usdt(timeout: float | None = None) -> ExirUsdtQuote:
    query = urlencode({"symbol": EXIR_SYMBOL})
    payload = fetch_json_direct_then_price_proxy(
        f"{EXIR_ORDERBOOK_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
        timeout=timeout,
    )
    return parse_exir_usdt_orderbook(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_qty(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def build_exir_usdt_post(quote: ExirUsdtQuote) -> str:
    spread = quote.best_ask_toman - quote.best_bid_toman
    lines = [
        "💎 <b>تتر | اکسیر</b>",
        "",
        f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_ask_toman)}</code> تومان",
        f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_bid_toman)}</code> تومان",
        "",
        f"📦 <b>حجم بهترین فروش</b>　<code>{_fmt_qty(quote.best_ask_quantity)}</code> USDT",
        f"📦 <b>حجم بهترین خرید</b>　<code>{_fmt_qty(quote.best_bid_quantity)}</code> USDT",
        f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
    ]
    if quote.source_timestamp:
        lines.append(f"🕒 <b>زمان منبع</b>　<code>{quote.source_timestamp}</code>")
    return "\n".join(lines)
