#!/usr/bin/env python3
"""Direct Nobitex USDT/IRR market adapter for AlanChande."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NOBITEX_STATS_URL = "https://apiv2.nobitex.ir/market/stats"


@dataclass(frozen=True)
class NobitexUsdtQuote:
    best_sell_rial: Decimal
    best_buy_rial: Decimal
    latest_rial: Decimal
    day_high_rial: Decimal
    day_low_rial: Decimal
    day_change_pct: Decimal

    @property
    def best_sell_toman(self) -> Decimal:
        return self.best_sell_rial / Decimal("10")

    @property
    def best_buy_toman(self) -> Decimal:
        return self.best_buy_rial / Decimal("10")

    @property
    def latest_toman(self) -> Decimal:
        return self.latest_rial / Decimal("10")

    @property
    def day_high_toman(self) -> Decimal:
        return self.day_high_rial / Decimal("10")

    @property
    def day_low_toman(self) -> Decimal:
        return self.day_low_rial / Decimal("10")


def _decimal(value, field: str, *, allow_negative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Nobitex field {field!r} is not numeric") from exc

    if not result.is_finite():
        raise ValueError(f"Nobitex field {field!r} is not finite")
    if allow_negative:
        return result
    if result <= 0:
        raise ValueError(f"Nobitex field {field!r} must be positive")
    return result


def parse_nobitex_usdt_stats(payload: dict) -> NobitexUsdtQuote:
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("Nobitex market stats response status is not ok")

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("Nobitex market stats response has no stats object")

    market = stats.get("usdt-rls")
    if not isinstance(market, dict):
        raise ValueError("Nobitex response has no usdt-rls market")

    if market.get("isClosed") is True:
        raise ValueError("Nobitex usdt-rls market is closed")

    return NobitexUsdtQuote(
        best_sell_rial=_decimal(market.get("bestSell"), "bestSell"),
        best_buy_rial=_decimal(market.get("bestBuy"), "bestBuy"),
        latest_rial=_decimal(market.get("latest"), "latest"),
        day_high_rial=_decimal(market.get("dayHigh"), "dayHigh"),
        day_low_rial=_decimal(market.get("dayLow"), "dayLow"),
        day_change_pct=_decimal(market.get("dayChange", "0"), "dayChange", allow_negative=True),
    )


def fetch_nobitex_usdt(timeout: int = 20) -> NobitexUsdtQuote:
    query = urlencode({"srcCurrency": "usdt", "dstCurrency": "rls"})
    request = Request(
        f"{NOBITEX_STATS_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Nobitex returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load Nobitex market stats: {exc}") from exc

    return parse_nobitex_usdt_stats(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    arrow = "🔼" if rounded > 0 else "🔻" if rounded < 0 else "⚪️"
    return f"{arrow} {abs(rounded):.2f}%".rstrip("0").rstrip(".")


def build_nobitex_usdt_post(quote: NobitexUsdtQuote) -> str:
    return "\n".join(
        [
            "💎 <b>تتر | نوبیتکس</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.best_sell_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.best_buy_toman)}</code> تومان",
            "",
            f"🔹 آخرین معامله　<code>{_fmt_toman(quote.latest_toman)}</code>",
            f"📈 سقف روز　<code>{_fmt_toman(quote.day_high_toman)}</code>",
            f"📉 کف روز　<code>{_fmt_toman(quote.day_low_toman)}</code>",
            f"📊 تغییر روز　<code>{_fmt_pct(quote.day_change_pct)}</code>",
        ]
    )
