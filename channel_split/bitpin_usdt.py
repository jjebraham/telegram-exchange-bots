#!/usr/bin/env python3
"""Direct Bitpin USDT/IRT order-book adapter for AlanChande.

Public endpoints used:
- GET /v1/mkt/markets/?page=N
- GET /v2/mth/actives/{market_id}/?type=buy|sell

The USDT/IRT market id is discovered dynamically from the markets feed.
No Bitpin account credentials are required for these public market-data calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from price_proxy import fetch_json_direct_then_price_proxy

BITPIN_API_URL = "https://api.bitpin.ir"
BITPIN_MARKETS_URL = BITPIN_API_URL + "/v1/mkt/markets/?page={page}"
BITPIN_ORDERBOOK_URL = BITPIN_API_URL + "/v2/mth/actives/{market_id}/?type={side}"
BITPIN_USDT_IRT_CODE = "USDT_IRT"


@dataclass(frozen=True)
class BitpinUsdtQuote:
    market_id: int
    best_ask_toman: Decimal
    best_ask_quantity: Decimal
    best_bid_toman: Decimal
    best_bid_quantity: Decimal


def _positive_decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Bitpin field {field!r} is not numeric") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError(f"Bitpin field {field!r} must be positive")
    return result


def parse_bitpin_usdt_market_id(payload: dict) -> int | None:
    if not isinstance(payload, dict):
        raise ValueError("Bitpin markets response is not an object")

    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Bitpin markets response has no results list")

    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("code", "")).upper() != BITPIN_USDT_IRT_CODE:
            continue
        market_id = item.get("id")
        try:
            market_id = int(market_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Bitpin USDT_IRT market id is invalid") from exc
        if market_id <= 0:
            raise ValueError("Bitpin USDT_IRT market id must be positive")
        return market_id

    return None


def _parse_side(payload: dict, side: str) -> tuple[Decimal, Decimal]:
    if not isinstance(payload, dict):
        raise ValueError(f"Bitpin {side} order-book response is not an object")

    orders = payload.get("orders")
    if not isinstance(orders, list) or not orders:
        raise ValueError(f"Bitpin {side} order book has no orders")

    parsed: list[tuple[Decimal, Decimal]] = []
    for index, order in enumerate(orders):
        if not isinstance(order, dict):
            continue
        try:
            price = _positive_decimal(order.get("price"), f"{side}.orders[{index}].price")
            quantity_raw = order.get("remain")
            if quantity_raw in (None, "", "0", 0):
                quantity_raw = order.get("amount")
            quantity = _positive_decimal(
                quantity_raw,
                f"{side}.orders[{index}].quantity",
            )
        except ValueError:
            continue
        parsed.append((price, quantity))

    if not parsed:
        raise ValueError(f"Bitpin {side} order book has no usable orders")

    if side == "sell":
        return min(parsed, key=lambda row: row[0])
    if side == "buy":
        return max(parsed, key=lambda row: row[0])
    raise ValueError(f"Unsupported Bitpin side: {side}")


def parse_bitpin_usdt_orderbooks(
    market_id: int,
    buy_payload: dict,
    sell_payload: dict,
) -> BitpinUsdtQuote:
    best_bid, best_bid_quantity = _parse_side(buy_payload, "buy")
    best_ask, best_ask_quantity = _parse_side(sell_payload, "sell")

    if best_bid >= best_ask:
        raise ValueError("Bitpin order book is crossed or invalid")

    return BitpinUsdtQuote(
        market_id=market_id,
        best_ask_toman=best_ask,
        best_ask_quantity=best_ask_quantity,
        best_bid_toman=best_bid,
        best_bid_quantity=best_bid_quantity,
    )


def fetch_bitpin_market_id(timeout: float | None = None, max_pages: int = 10) -> int:
    next_url: str | None = BITPIN_MARKETS_URL.format(page=1)

    for _ in range(max_pages):
        if not next_url:
            break

        payload = fetch_json_direct_then_price_proxy(
            next_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AlanChande-DirectMarket/1.0",
            },
            timeout=timeout,
        )

        market_id = parse_bitpin_usdt_market_id(payload)
        if market_id is not None:
            return market_id

        candidate = payload.get("next")
        next_url = candidate if isinstance(candidate, str) and candidate.startswith("https://") else None

    raise ValueError("Bitpin USDT_IRT market was not found")


def fetch_bitpin_usdt(timeout: float | None = None) -> BitpinUsdtQuote:
    market_id = fetch_bitpin_market_id(timeout=timeout)

    common_headers = {
        "Accept": "application/json",
        "User-Agent": "AlanChande-DirectMarket/1.0",
    }

    buy_payload = fetch_json_direct_then_price_proxy(
        BITPIN_ORDERBOOK_URL.format(market_id=market_id, side="buy"),
        headers=common_headers,
        timeout=timeout,
    )
    sell_payload = fetch_json_direct_then_price_proxy(
        BITPIN_ORDERBOOK_URL.format(market_id=market_id, side="sell"),
        headers=common_headers,
        timeout=timeout,
    )

    return parse_bitpin_usdt_orderbooks(market_id, buy_payload, sell_payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_qty(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def build_bitpin_usdt_post(quote: BitpinUsdtQuote) -> str:
    spread = quote.best_ask_toman - quote.best_bid_toman
    return "\n".join(
        [
            "💎 <b>تتر | بیت‌پین</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_ask_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_bid_toman)}</code> تومان",
            "",
            f"📦 <b>حجم بهترین فروش</b>　<code>{_fmt_qty(quote.best_ask_quantity)}</code> USDT",
            f"📦 <b>حجم بهترین خرید</b>　<code>{_fmt_qty(quote.best_bid_quantity)}</code> USDT",
            f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
        ]
    )
