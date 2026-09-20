#!/usr/bin/env python3
"""Seven-exchange USDT board with per-row source fallback.

Priority for each exchange:
1. Direct exchange API (currently live: Wallex, Ramzinex, Exir)
2. TGJU exchange comparison
3. Ramzarz.news exchange table

The final Telegram board keeps one normalized customer-facing convention:
- buy_toman: what the customer pays to buy 1 USDT
- sell_toman: what the customer receives for selling 1 USDT
"""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from direct_usdt_compare import DirectUsdtQuote, collect_direct_usdt_quotes
from iran_usdt import UsdtExchangeQuote, fetch_usdt_exchange_quotes, filter_usdt_quotes
from ramzarz_usdt import RamzarzUsdtQuote, fetch_ramzarz_usdt_quotes

logger = logging.getLogger(__name__)

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

TARGET_EXCHANGES = (
    "والکس",
    "نوبیتکس",
    "رمزینکس",
    "بیت پین",
    "آبان تتر",
    "تبدیل",
    "اکسیر",
)

DISPLAY_EXCHANGE_NAMES = {
    "والکس": "Wallex",
    "نوبیتکس": "Nobitex",
    "رمزینکس": "Ramzinex",
    "بیت پین": "Bitpin",
    "آبان تتر": "AbanTether",
    "تبدیل": "Tabdeal",
    "اکسیر": "Exir",
}


@dataclass(frozen=True)
class HybridUsdtQuote:
    exchange: str
    buy_toman: Decimal
    sell_toman: Decimal | None
    change_pct: Decimal | None
    source: str
    source_time: str | None = None


def _safe_direct() -> tuple[list[DirectUsdtQuote], dict[str, str]]:
    try:
        return collect_direct_usdt_quotes(min_sources=1)
    except Exception as exc:
        logger.warning("All direct USDT sources failed: %s: %s", type(exc).__name__, exc)
        return [], {"direct": f"{type(exc).__name__}: {exc}"[:300]}


def _safe_tgju() -> list[UsdtExchangeQuote]:
    try:
        return filter_usdt_quotes(fetch_usdt_exchange_quotes())
    except Exception as exc:
        logger.warning("TGJU USDT source failed: %s: %s", type(exc).__name__, exc)
        return []


def _safe_ramzarz() -> list[RamzarzUsdtQuote]:
    try:
        return fetch_ramzarz_usdt_quotes()
    except Exception as exc:
        logger.warning("Ramzarz USDT source failed: %s: %s", type(exc).__name__, exc)
        return []


def _valid_customer_pair(
    buy_toman: Decimal,
    sell_toman: Decimal | None,
) -> bool:
    return sell_toman is None or sell_toman < buy_toman


def merge_hybrid_usdt_quotes(
    direct_quotes: list[DirectUsdtQuote],
    tgju_quotes: list[UsdtExchangeQuote],
    ramzarz_quotes: list[RamzarzUsdtQuote],
    *,
    min_exchanges: int = 5,
    max_median_deviation: Decimal = Decimal("0.08"),
) -> list[HybridUsdtQuote]:
    direct_by_name = {q.exchange: q for q in direct_quotes}
    tgju_by_name = {q.exchange: q for q in tgju_quotes}
    ramzarz_by_name = {q.exchange: q for q in ramzarz_quotes}

    merged: list[HybridUsdtQuote] = []

    for exchange in TARGET_EXCHANGES:
        direct = direct_by_name.get(exchange)
        tgju = tgju_by_name.get(exchange)
        ramzarz = ramzarz_by_name.get(exchange)

        if direct is not None:
            merged.append(
                HybridUsdtQuote(
                    exchange=exchange,
                    buy_toman=direct.buy_toman,
                    sell_toman=direct.sell_toman,
                    change_pct=tgju.change_pct if tgju else None,
                    source="direct",
                    source_time=tgju.source_time if tgju else None,
                )
            )
            continue

        if tgju is not None:
            buy_toman = tgju.sell_toman
            sell_toman = tgju.buy_toman
            source = "tgju"

            # Some aggregator rows can briefly expose a crossed customer pair
            # (customer sell >= customer buy). Prefer Ramzarz's complete
            # two-sided quote when it is available and internally valid.
            if not _valid_customer_pair(buy_toman, sell_toman):
                if (
                    ramzarz is not None
                    and _valid_customer_pair(
                        ramzarz.buy_toman,
                        ramzarz.sell_toman,
                    )
                ):
                    buy_toman = ramzarz.buy_toman
                    sell_toman = ramzarz.sell_toman
                    source = "ramzarz"
                else:
                    sell_toman = None
                    source = "tgju"
            elif sell_toman is None and ramzarz is not None:
                if _valid_customer_pair(buy_toman, ramzarz.sell_toman):
                    sell_toman = ramzarz.sell_toman
                    source = "tgju+ramzarz"

            merged.append(
                HybridUsdtQuote(
                    exchange=exchange,
                    buy_toman=buy_toman,
                    sell_toman=sell_toman,
                    change_pct=tgju.change_pct,
                    source=source,
                    source_time=tgju.source_time,
                )
            )
            continue

        if ramzarz is not None:
            merged.append(
                HybridUsdtQuote(
                    exchange=exchange,
                    buy_toman=ramzarz.buy_toman,
                    sell_toman=ramzarz.sell_toman,
                    change_pct=None,
                    source="ramzarz",
                )
            )

    if len(merged) >= 3:
        median = Decimal(
            str(statistics.median([float(q.buy_toman) for q in merged]))
        )
        if median > 0:
            lower = median * (Decimal("1") - max_median_deviation)
            upper = median * (Decimal("1") + max_median_deviation)
            merged = [q for q in merged if lower <= q.buy_toman <= upper]

    if len(merged) < min_exchanges:
        raise RuntimeError(
            f"Only {len(merged)} of {len(TARGET_EXCHANGES)} target USDT exchanges available"
        )

    order = {name: idx for idx, name in enumerate(TARGET_EXCHANGES)}
    merged.sort(key=lambda q: order[q.exchange])
    return merged


def collect_hybrid_usdt_quotes() -> list[HybridUsdtQuote]:
    # The three source families are independent and can be fetched in parallel.
    with ThreadPoolExecutor(max_workers=3) as executor:
        direct_future = executor.submit(_safe_direct)
        tgju_future = executor.submit(_safe_tgju)
        ramzarz_future = executor.submit(_safe_ramzarz)

        direct_quotes, direct_errors = direct_future.result()
        tgju_quotes = tgju_future.result()
        ramzarz_quotes = ramzarz_future.result()

    quotes = merge_hybrid_usdt_quotes(
        direct_quotes,
        tgju_quotes,
        ramzarz_quotes,
    )

    mapping = ", ".join(f"{q.exchange}={q.source}" for q in quotes)
    logger.info("Hybrid USDT source mapping: %s", mapping)
    if direct_errors:
        logger.info("Direct USDT partial errors: %s", ", ".join(sorted(direct_errors)))

    return quotes


def _fmt_toman(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    rounded = value.quantize(Decimal("0.01"))
    arrow = "🔼" if rounded > 0 else "🔻" if rounded < 0 else "⚪️"
    return f" {arrow} <code>{abs(rounded):.2f}%</code>"


def _fmt_table_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    rounded = value.quantize(Decimal("0.01"))
    if rounded > 0:
        return f"+{rounded:.2f}%"
    if rounded < 0:
        return f"-{abs(rounded):.2f}%"
    return "0.00%"


def _display_exchange(exchange: str) -> str:
    return DISPLAY_EXCHANGE_NAMES.get(exchange, exchange)


def build_hybrid_usdt_post(quotes: list[HybridUsdtQuote]) -> str:
    if not quotes:
        raise ValueError("No hybrid USDT quotes")

    direct_count = sum(1 for q in quotes if q.source == "direct")
    fallback_count = len(quotes) - direct_count

    buy_average = sum((q.buy_toman for q in quotes), Decimal("0")) / Decimal(len(quotes))
    sell_values = [q.sell_toman for q in quotes if q.sell_toman is not None]

    lowest_buy = min(quotes, key=lambda q: q.buy_toman)
    valid_sell_quotes = [q for q in quotes if q.sell_toman is not None]
    highest_sell = (
        max(valid_sell_quotes, key=lambda q: q.sell_toman or Decimal("0"))
        if valid_sell_quotes
        else None
    )
    sell_average = (
        sum((value for value in sell_values if value is not None), Decimal("0"))
        / Decimal(len(sell_values))
        if sell_values
        else None
    )

    table_lines = [
        f"{'EXCHANGE':<10} {'SELL':>7} {'BUY':>7} {'Δ24H':>6}",
    ]
    for quote in quotes:
        table_lines.append(
            f"{_display_exchange(quote.exchange):<10} "
            f"{_fmt_toman(quote.buy_toman):>7} "
            f"{_fmt_toman(quote.sell_toman):>7} "
            f"{_fmt_table_pct(quote.change_pct):>6}"
        )

    lines = [
        "💎 <b>قیمت تتر در صرافی‌های ایران</b>",
        "",
        "🔴 SELL = فروش به شما　•　🟢 BUY = خرید از شما",
        "",
        "<pre>" + "\n".join(table_lines) + "</pre>",
        "",
        f"🛒 کمترین قیمت خرید: <b>{_display_exchange(lowest_buy.exchange)}</b>　"
        f"<code>{_fmt_toman(lowest_buy.buy_toman)}</code> تومان",
    ]

    if highest_sell is not None:
        lines.append(
            f"💰 بیشترین قیمت فروش: <b>{_display_exchange(highest_sell.exchange)}</b>　"
            f"<code>{_fmt_toman(highest_sell.sell_toman)}</code> تومان"
        )

    lines.extend(
        [
            "",
            f"✅ <b>{len(quotes)}/{len(TARGET_EXCHANGES)}</b>　"
            f"🌐 مستقیم <b>{direct_count}</b>　🧩 پشتیبان <b>{fallback_count}</b>",
            f"🕒 <code>{datetime.now(TEHRAN_TZ).strftime('%H:%M')}</code> تهران",
            "قیمت‌ها صرفاً جهت اطلاع‌رسانی است.",
        ]
    )
    return "\n".join(lines)


def fetch_and_build_hybrid_usdt_post() -> str:
    return build_hybrid_usdt_post(collect_hybrid_usdt_quotes())
