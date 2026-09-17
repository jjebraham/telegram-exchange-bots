from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Mapping

from .models import BankRate


CURRENCY_FA = {
    "USD": "دلار",
    "EUR": "یورو",
    "GBP": "پوند",
}


def render_bank_comparison(rates: list[BankRate], currency: str) -> str:
    if not rates:
        raise ValueError("No bank rates to render")

    code = currency.upper()
    label = CURRENCY_FA.get(code, code)
    ordered = sorted(rates, key=lambda item: item.sell)
    now = datetime.now().astimezone().strftime("%H:%M")

    lines = [
        f"🏦 <b>{escape(label)} امروز کجا ارزان‌تره؟</b>",
        "",
        f"برای <b>خرید {escape(code)} با لیر</b> — نرخ فروش بانک/بازار به مشتری:",
        "",
    ]

    medals = ["🥇", "🥈", "🥉"]
    for index, rate in enumerate(ordered):
        prefix = medals[index] if index < len(medals) else "▫️"
        lines.append(
            f"{prefix} <b>{escape(rate.institution)}</b> — {rate.sell:,.4f} TL"
        )

    best = ordered[0]
    worst = ordered[-1]
    difference = worst.sell - best.sell
    saving_1000 = difference * 1000

    lines.extend(
        [
            "",
            f"💡 اختلاف بهترین و بالاترین نرخ این لیست برای ۱٬۰۰۰ {escape(code)}: "
            f"<b>{saving_1000:,.2f} TL</b>",
            "",
            f"🕒 بروزرسانی: {now}",
            "ℹ️ نرخ‌ها اطلاعاتی هستند و نرخ نهایی بانک می‌تواند بر اساس کانال، مبلغ و زمان معامله تغییر کند.",
            "#نرخ_دلار #بانک_ترکیه #کاپالی_چارشی" if code == "USD" else "#نرخ_ارز #بانک_ترکیه",
        ]
    )
    return "\n".join(lines)


def render_kiani_rates(rates: Mapping[str, Mapping[str, float]]) -> str:
    if not rates:
        raise ValueError("No Kiani rates to render")

    display_order = ["TRY", "USD", "EUR", "USDT"]
    labels = {
        "TRY": "🇹🇷 لیر",
        "USD": "🇺🇸 دلار",
        "EUR": "🇪🇺 یورو",
        "USDT": "🟢 تتر",
    }

    lines = [
        "💱 <b>نرخ خرید و فروش صرافی کیانی</b>",
        "",
    ]

    for code in display_order:
        item = rates.get(code)
        if not item:
            continue
        buy = float(item["buy"])
        sell = float(item["sell"])
        lines.extend(
            [
                f"<b>{labels[code]}</b>",
                f"خرید از شما: <b>{buy:,.0f}</b>",
                f"فروش به شما: <b>{sell:,.0f}</b>",
                "",
            ]
        )

    lines.extend(
        [
            "⚠️ قبل از واریز، نرخ و اطلاعات حساب را از مسیر رسمی تأیید کنید.",
            "🤖 ثبت سفارش: @KianiExchangeBot",
            "📊 نرخ‌های مرجع بازار: @alanchande_com",
        ]
    )
    return "\n".join(lines)
