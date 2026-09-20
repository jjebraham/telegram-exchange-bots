#!/usr/bin/env python3
"""Compact 24-hour Turkey FX pulse for AlanChande."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def _kapalicarsi(quotes: list[Any]) -> Any:
    quote = next((q for q in quotes if q.name == "Kapalıçarşı"), None)
    if quote is None:
        raise ValueError("Kapalıçarşı quote is required for FX pulse")
    return quote


def _midpoint(buy: Decimal, sell: Decimal) -> Decimal:
    return (buy + sell) / Decimal("2")


def _fmt_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001')):.4f}"


def _fmt_change(
    current_buy: Decimal,
    current_sell: Decimal,
    previous: tuple[Decimal, Decimal] | None,
) -> str:
    if previous is None:
        return "—"

    previous_mid = _midpoint(previous[0], previous[1])
    if previous_mid == 0:
        return "—"

    current_mid = _midpoint(current_buy, current_sell)
    change = ((current_mid - previous_mid) / previous_mid) * Decimal("100")
    rounded = change.quantize(Decimal("0.01"))
    if rounded > 0:
        return f"+{rounded:.2f}%"
    return f"{rounded:.2f}%"


def build_turkey_fx_pulse_post(
    usd_quotes: list[Any],
    eur_quotes: list[Any],
    previous_usd: Mapping[str, tuple[Decimal, Decimal]] | None = None,
    previous_eur: Mapping[str, tuple[Decimal, Decimal]] | None = None,
    *,
    now: datetime | None = None,
) -> str:
    usd = _kapalicarsi(usd_quotes)
    eur = _kapalicarsi(eur_quotes)

    previous_usd = previous_usd or {}
    previous_eur = previous_eur or {}

    usd_mid = _midpoint(usd.buy, usd.sell)
    eur_mid = _midpoint(eur.buy, eur.sell)

    table_lines = [
        f"{'MARKET':<8} {'RATE':>8} {'Δ24H':>7}",
        f"{'USD/TRY':<8} {_fmt_rate(usd_mid):>8} "
        f"{_fmt_change(usd.buy, usd.sell, previous_usd.get('Kapalıçarşı')):>7}",
        f"{'EUR/TRY':<8} {_fmt_rate(eur_mid):>8} "
        f"{_fmt_change(eur.buy, eur.sell, previous_eur.get('Kapalıçarşı')):>7}",
    ]

    local_now = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)

    return "\n".join(
        [
            "📊 <b>نبض بازار ارز ترکیه | 24H</b>",
            "",
            "🏛️ نرخ میانی Kapalıçarşı",
            "",
            "<pre>" + "\n".join(table_lines) + "</pre>",
            "",
            f"🕒 <code>{local_now.strftime('%H:%M')}</code> استانبول",
            "قیمت‌ها صرفاً جهت اطلاع‌رسانی است.",
        ]
    )
