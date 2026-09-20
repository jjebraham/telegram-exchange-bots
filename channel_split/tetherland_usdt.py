#!/usr/bin/env python3
"""Direct Tetherland USDT/Toman reference-price adapter for AlanChande.

Endpoint:
GET https://api.tetherland.com/currencies

This feed exposes a single USDT reference/current price rather than separate
best bid/ask. It must therefore remain a reference-price source in comparison
posts and must not be presented as an executable buy/sell quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from price_proxy import fetch_json_direct_then_price_proxy

TETHERLAND_CURRENCIES_URL = "https://api.tetherland.com/currencies"


@dataclass(frozen=True)
class TetherlandUsdtQuote:
    price_toman: Decimal
    change_24h_pct: Decimal | None
    last_24h_toman: Decimal | None


def _decimal(
    value,
    field: str,
    *,
    optional: bool = False,
    allow_negative: bool = False,
) -> Decimal | None:
    if optional and value in (None, "", "-"):
        return None

    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Tetherland field {field!r} is not numeric") from exc

    if not result.is_finite():
        raise ValueError(f"Tetherland field {field!r} is not finite")

    if allow_negative:
        return result

    if result <= 0:
        raise ValueError(f"Tetherland field {field!r} must be positive")
    return result


def parse_tetherland_usdt(payload: dict) -> TetherlandUsdtQuote:
    if not isinstance(payload, dict):
        raise ValueError("Tetherland currencies response is not an object")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Tetherland response has no data object")

    currencies = data.get("currencies")
    if not isinstance(currencies, dict):
        raise ValueError("Tetherland response has no currencies object")

    usdt = currencies.get("USDT")
    if not isinstance(usdt, dict):
        raise ValueError("Tetherland response has no USDT object")

    price = _decimal(usdt.get("price"), "price")
    assert isinstance(price, Decimal)

    change = _decimal(
        usdt.get("diff24d"),
        "diff24d",
        optional=True,
        allow_negative=True,
    )
    last_24h = _decimal(
        usdt.get("last24h"),
        "last24h",
        optional=True,
    )

    return TetherlandUsdtQuote(
        price_toman=price,
        change_24h_pct=change,
        last_24h_toman=last_24h,
    )


def fetch_tetherland_usdt(timeout: float | None = None) -> TetherlandUsdtQuote:
    payload = fetch_json_direct_then_price_proxy(
        TETHERLAND_CURRENCIES_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
        timeout=timeout,
    )
    return parse_tetherland_usdt(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    arrow = "🔼" if rounded > 0 else "🔻" if rounded < 0 else "⚪️"
    return f"{arrow} {abs(rounded):.2f}%"


def build_tetherland_usdt_post(quote: TetherlandUsdtQuote) -> str:
    lines = [
        "💎 <b>تتر | تترلند</b>",
        "",
        f"💰 <b>نرخ مرجع</b>　<code>{_fmt_toman(quote.price_toman)}</code> تومان",
    ]

    if quote.change_24h_pct is not None:
        lines.append(
            f"📊 <b>تغییر ۲۴ ساعت</b>　<code>{_fmt_pct(quote.change_24h_pct)}</code>"
        )

    lines.extend(
        [
            "",
            "ℹ️ این منبع یک نرخ مرجع نمایش می‌دهد؛ نه بهترین سفارش خرید/فروش.",
        ]
    )
    return "\n".join(lines)
