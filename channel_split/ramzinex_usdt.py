#!/usr/bin/env python3
"""Direct Ramzinex USDT/IRR order-book adapter for AlanChande.

Public endpoints:
- GET https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/pairs
- GET https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/orderbooks/{pair_id}/buys_sells

Ramzinex quotes this market in IRR, so prices are divided by 10 before
displaying Toman values.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from price_proxy import fetch_json_direct_then_price_proxy

RAMZINEX_BASE_URL = "https://publicapi.ramzinex.com/exchange/api/v1.0/exchange"
RAMZINEX_PAIRS_URL = RAMZINEX_BASE_URL + "/pairs"
RAMZINEX_ORDERBOOK_URL = RAMZINEX_BASE_URL + "/orderbooks/{pair_id}/buys_sells"


@dataclass(frozen=True)
class RamzinexUsdtQuote:
    pair_id: int
    best_ask_toman: Decimal
    best_ask_quantity: Decimal
    best_bid_toman: Decimal
    best_bid_quantity: Decimal


def _positive_decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Ramzinex field {field!r} is not numeric") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError(f"Ramzinex field {field!r} must be positive")
    return result


def _symbol_en(value) -> str:
    if isinstance(value, dict):
        return str(value.get("en", "")).strip().lower()
    return str(value or "").strip().lower()


def parse_ramzinex_usdt_pair_id(payload: dict) -> int:
    if not isinstance(payload, dict) or payload.get("status") != 0:
        raise ValueError("Ramzinex pairs response status is not successful")

    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("Ramzinex pairs response has no data list")

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("is_delist") or row.get("is_temporarily_suspended"):
            continue

        base = _symbol_en(row.get("base_currency_symbol"))
        quote = _symbol_en(row.get("quote_currency_symbol"))
        if base != "usdt" or quote != "irr":
            continue

        try:
            pair_id = int(row.get("pair_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Ramzinex USDT/IRR pair id is invalid") from exc

        if pair_id <= 0:
            raise ValueError("Ramzinex USDT/IRR pair id must be positive")
        return pair_id

    raise ValueError("Ramzinex USDT/IRR pair was not found")


def _parse_entries(entries, side: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(entries, list):
        raise ValueError(f"Ramzinex {side} order list is missing")

    parsed: list[tuple[Decimal, Decimal]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        try:
            price_rial = _positive_decimal(entry[0], f"{side}[{index}].price")
            quantity = _positive_decimal(entry[1], f"{side}[{index}].quantity")
        except ValueError:
            continue
        parsed.append((price_rial / Decimal("10"), quantity))

    if not parsed:
        raise ValueError(f"Ramzinex {side} order list has no usable rows")
    return parsed


def parse_ramzinex_usdt_orderbook(pair_id: int, payload: dict) -> RamzinexUsdtQuote:
    if not isinstance(payload, dict):
        raise ValueError("Ramzinex order-book response is not an object")

    # Current per-pair endpoint returns {status: 0, data: {buys: [], sells: []}}.
    # Accept the inner object directly too so this stays compatible with the
    # all-orderbooks response shape.
    if "status" in payload and payload.get("status") != 0:
        raise ValueError("Ramzinex order-book response status is not successful")

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("Ramzinex order-book response has no data object")

    buys = _parse_entries(data.get("buys"), "buys")
    sells = _parse_entries(data.get("sells"), "sells")

    best_bid_toman, best_bid_quantity = max(buys, key=lambda row: row[0])
    best_ask_toman, best_ask_quantity = min(sells, key=lambda row: row[0])

    if best_bid_toman >= best_ask_toman:
        raise ValueError("Ramzinex order book is crossed or invalid")

    return RamzinexUsdtQuote(
        pair_id=pair_id,
        best_ask_toman=best_ask_toman,
        best_ask_quantity=best_ask_quantity,
        best_bid_toman=best_bid_toman,
        best_bid_quantity=best_bid_quantity,
    )


def fetch_ramzinex_usdt(timeout: float | None = None) -> RamzinexUsdtQuote:
    headers = {
        "Accept": "application/json",
        "User-Agent": "AlanChande-DirectMarket/1.0",
    }

    pairs_payload = fetch_json_direct_then_price_proxy(
        RAMZINEX_PAIRS_URL,
        headers=headers,
        timeout=timeout,
    )
    pair_id = parse_ramzinex_usdt_pair_id(pairs_payload)

    book_payload = fetch_json_direct_then_price_proxy(
        RAMZINEX_ORDERBOOK_URL.format(pair_id=pair_id),
        headers=headers,
        timeout=timeout,
    )
    return parse_ramzinex_usdt_orderbook(pair_id, book_payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_qty(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def build_ramzinex_usdt_post(quote: RamzinexUsdtQuote) -> str:
    spread = quote.best_ask_toman - quote.best_bid_toman
    return "\n".join(
        [
            "💎 <b>تتر | رمزینکس</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_ask_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_bid_toman)}</code> تومان",
            "",
            f"📦 <b>حجم بهترین فروش</b>　<code>{_fmt_qty(quote.best_ask_quantity)}</code> USDT",
            f"📦 <b>حجم بهترین خرید</b>　<code>{_fmt_qty(quote.best_bid_quantity)}</code> USDT",
            f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
        ]
    )
