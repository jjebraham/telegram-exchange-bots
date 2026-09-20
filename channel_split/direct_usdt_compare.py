#!/usr/bin/env python3
"""Combined direct-source USDT comparison for AlanChande.

Confirmed live sources:
- Wallex
- Exir
- Ramzinex

Each source is fetched independently so a single outage does not kill the
whole comparison. Fetches run concurrently to avoid stacking provider timeouts.

Semantics:
- buy_toman: price a customer pays to BUY one USDT (best ask / exchange sell)
- sell_toman: price a customer receives to SELL one USDT (best bid / exchange buy)
"""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from exir_usdt import fetch_exir_usdt
from ramzinex_usdt import fetch_ramzinex_usdt
from wallex_usdt import fetch_wallex_usdt

logger = logging.getLogger(__name__)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


@dataclass(frozen=True)
class DirectUsdtQuote:
    exchange: str
    buy_toman: Decimal
    sell_toman: Decimal
    buy_quantity: Decimal | None = None
    sell_quantity: Decimal | None = None

    @property
    def midpoint_toman(self) -> Decimal:
        return (self.buy_toman + self.sell_toman) / Decimal("2")

    @property
    def spread_toman(self) -> Decimal:
        return self.buy_toman - self.sell_toman


def _from_wallex() -> DirectUsdtQuote:
    quote = fetch_wallex_usdt()
    return DirectUsdtQuote(
        exchange="والکس",
        buy_toman=quote.best_ask_toman,
        sell_toman=quote.best_bid_toman,
    )


def _from_exir() -> DirectUsdtQuote:
    quote = fetch_exir_usdt()
    return DirectUsdtQuote(
        exchange="اکسیر",
        buy_toman=quote.best_ask_toman,
        sell_toman=quote.best_bid_toman,
        buy_quantity=quote.best_ask_quantity,
        sell_quantity=quote.best_bid_quantity,
    )


def _from_ramzinex() -> DirectUsdtQuote:
    quote = fetch_ramzinex_usdt()
    return DirectUsdtQuote(
        exchange="رمزینکس",
        buy_toman=quote.best_ask_toman,
        sell_toman=quote.best_bid_toman,
        buy_quantity=quote.best_ask_quantity,
        sell_quantity=quote.best_bid_quantity,
    )


DEFAULT_FETCHERS: tuple[tuple[str, Callable[[], DirectUsdtQuote]], ...] = (
    ("Wallex", _from_wallex),
    ("Exir", _from_exir),
    ("Ramzinex", _from_ramzinex),
)


def _validate_quote(quote: DirectUsdtQuote) -> DirectUsdtQuote:
    if quote.buy_toman <= 0 or quote.sell_toman <= 0:
        raise ValueError(f"{quote.exchange} returned a non-positive price")
    if quote.sell_toman >= quote.buy_toman:
        raise ValueError(f"{quote.exchange} returned crossed buy/sell prices")
    return quote


def filter_direct_usdt_outliers(
    quotes: list[DirectUsdtQuote],
    *,
    max_median_deviation: Decimal = Decimal("0.08"),
) -> list[DirectUsdtQuote]:
    """Drop sources whose midpoint is far from the cross-source median."""
    if len(quotes) < 3:
        return list(quotes)

    midpoint_values = [float(q.midpoint_toman) for q in quotes]
    median = Decimal(str(statistics.median(midpoint_values)))
    if median <= 0:
        return list(quotes)

    lower = median * (Decimal("1") - max_median_deviation)
    upper = median * (Decimal("1") + max_median_deviation)
    return [q for q in quotes if lower <= q.midpoint_toman <= upper]


def collect_direct_usdt_quotes(
    fetchers: tuple[tuple[str, Callable[[], DirectUsdtQuote]], ...] = DEFAULT_FETCHERS,
    *,
    min_sources: int = 2,
) -> tuple[list[DirectUsdtQuote], dict[str, str]]:
    """Fetch providers concurrently and isolate individual failures."""
    quotes: list[DirectUsdtQuote] = []
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(fetchers) or 1) as executor:
        future_to_name = {
            executor.submit(fetcher): name
            for name, fetcher in fetchers
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                quote = _validate_quote(future.result())
                quotes.append(quote)
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning(
                    "Direct USDT source %s failed: %s",
                    name,
                    errors[name],
                )

    quotes = filter_direct_usdt_outliers(quotes)

    if len(quotes) < min_sources:
        failure_text = ", ".join(sorted(errors)) or "outlier filtering"
        raise RuntimeError(
            f"Only {len(quotes)} direct USDT sources available; "
            f"need at least {min_sources}. Failed: {failure_text}"
        )

    # Stable display order rather than sorting by price, so the post does not
    # jump around visually every minute.
    order = {"والکس": 0, "رمزینکس": 1, "اکسیر": 2}
    quotes.sort(key=lambda q: order.get(q.exchange, 99))
    return quotes, errors


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def build_direct_usdt_comparison_post(
    quotes: list[DirectUsdtQuote],
    *,
    failed_source_count: int = 0,
    total_source_count: int = 3,
) -> str:
    if len(quotes) < 2:
        raise ValueError("At least two direct USDT quotes are required")

    avg_buy = sum((q.buy_toman for q in quotes), Decimal("0")) / Decimal(len(quotes))
    avg_sell = sum((q.sell_toman for q in quotes), Decimal("0")) / Decimal(len(quotes))

    lines = [
        "💎 <b>مقایسه مستقیم قیمت تتر</b>",
        "",
        "🏦 <b>صرافی</b>　　🛒 <b>خرید شما</b>　　💵 <b>فروش شما</b>",
        "",
    ]

    for quote in quotes:
        lines.append(
            f"• <b>{quote.exchange}</b>　"
            f"<code>{_fmt_toman(quote.buy_toman)}</code>　"
            f"<code>{_fmt_toman(quote.sell_toman)}</code>"
        )

    lines.extend(
        [
            "",
            f"➗ میانگین خرید　<code>{_fmt_toman(avg_buy)}</code> تومان",
            f"➗ میانگین فروش　<code>{_fmt_toman(avg_sell)}</code> تومان",
            "",
            f"📡 منابع فعال: <b>{len(quotes)}/{total_source_count}</b>",
            f"🕒 بروزرسانی: <code>{datetime.now(ISTANBUL_TZ).strftime('%H:%M')}</code> استانبول",
            "ℹ️ نرخ‌ها مستقیماً از API صرافی‌ها دریافت شده‌اند و بهترین قیمت لحظه‌ای بازار هستند.",
        ]
    )

    if failed_source_count:
        lines.append(
            f"⚠️ {failed_source_count} منبع در این بروزرسانی در دسترس نبود."
        )

    return "\n".join(lines)


def fetch_and_build_direct_usdt_comparison() -> str:
    quotes, errors = collect_direct_usdt_quotes()
    return build_direct_usdt_comparison_post(
        quotes,
        failed_source_count=len(errors),
        total_source_count=len(DEFAULT_FETCHERS),
    )
