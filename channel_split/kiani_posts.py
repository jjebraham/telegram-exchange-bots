#!/usr/bin/env python3
"""Customer-facing Kiani Exchange Telegram post formatters."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

PERSIAN_WEEKDAYS = (
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
)

JALALI_MONTHS = (
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def _fmt_int(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_cross(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}".rstrip("0").rstrip(".")


def _fmt_required_try(value: Decimal) -> str:
    # Keep small examples precise to the nearest lira, but round six-figure
    # TRY requirements to the nearest hundred for a cleaner customer example.
    quantum = Decimal("1E2") if value >= Decimal("100000") else Decimal("1")
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{int(rounded):,}"


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to Jalali without a third-party dependency."""
    g_days_in_month = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
    )
    for month_index in range(gm - 1):
        days += g_days_in_month[month_index]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        days += 1

    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def _jalali_timestamp(now: datetime | None = None) -> str:
    local = (now or datetime.now(ISTANBUL_TZ)).astimezone(ISTANBUL_TZ)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    weekday = PERSIAN_WEEKDAYS[local.weekday()]
    return (
        f"{weekday}، {jd} {JALALI_MONTHS[jm]} {jy} | "
        f"{local.strftime('%H:%M:%S')}"
    )


def build_kiani_try_post(
    rates: dict[str, Decimal],
    *,
    now: datetime | None = None,
    telegram_url: str = "https://t.me/TL905411603664",
    whatsapp_url: str = "https://wa.me/905392905686",
) -> str:
    """Build the customer-facing TRY/Toman transaction-rate post."""
    buy_from_us = rates["buy_lira"]
    sell_to_us = rates["sell_lira"]

    telegram_link = html.escape(telegram_url, quote=True)
    whatsapp_link = html.escape(whatsapp_url, quote=True)

    return "\n".join(
        [
            f"📆 <b>{html.escape(_jalali_timestamp(now))}</b>",
            "",
            "🇹🇷 <b>نرخ لیر ترکیه</b> به تومان 🇮🇷",
            "",
            "<pre>",
            f"🟩 BUY   TL {_fmt_int(buy_from_us)} = خرید لیر از ما",
            f"🟥 SELL  TL {_fmt_int(sell_to_us)} = فروش لیر به ما",
            "</pre>",
            "",
            "⚠️ <b>لطفاً قبل از واریز هماهنگ کنید:</b>",
            f'🔹 تلگرام: <a href="{telegram_link}">{telegram_link}</a>',
            f'🔹 واتس‌اپ: <a href="{whatsapp_link}">{whatsapp_link}</a>',
        ]
    )


def build_kiani_rate_post(
    rates: dict[str, Decimal],
    *,
    now: datetime | None = None,
    order_handle: str = "@Kianiexchangebot",
) -> str:
    """Compact Kiani customer transaction board."""
    local = (now or datetime.now(ISTANBUL_TZ)).astimezone(ISTANBUL_TZ)
    return "\n".join(
        [
            "<b>صرافی کیانی | نرخ امروز</b>",
            "",
            "🇹🇷 <b>لیر</b>",
            f"🟢 از ما می‌خرید: <b>{_fmt_int(rates['buy_lira'])}</b> تومان",
            f"🔵 به ما می‌فروشید: <b>{_fmt_int(rates['sell_lira'])}</b> تومان",
            "",
            "💵 <b>تتر</b>",
            f"🟢 از ما می‌خرید: <b>{_fmt_int(rates['buy_usdt'])}</b> تومان",
            f"🔵 به ما می‌فروشید: <b>{_fmt_int(rates['sell_usdt'])}</b> تومان",
            "",
            f"🔁 لیر ← تتر: <b>{_fmt_cross(rates['lira_to_usdt'])}</b> لیر",
            f"🔁 تتر ← لیر: <b>{_fmt_cross(rates['usdt_to_lira'])}</b> لیر",
            "",
            f"🕰 <code>{local.strftime('%H:%M')}</code> استانبول",
            f"👇 سفارش: {html.escape(order_handle)}",
        ]
    )


REMITTANCE_CURRENCIES = (
    ("USD", "🇺🇸", "دلار آمریکا"),
    ("EUR", "🇪🇺", "یورو"),
    ("GBP", "🇬🇧", "پوند انگلیس"),
    ("CAD", "🇨🇦", "دلار کانادا"),
    ("AUD", "🇦🇺", "دلار استرالیا"),
    ("SEK", "🇸🇪", "کرون سوئد"),
    ("TRY", "🇹🇷", "لیر ترکیه"),
)

PERSIAN_DIGITS = str.maketrans(
    "0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"
)


def _fmt_persian_toman(value: Decimal) -> str:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Remittance rates must be finite and positive")
    if amount != amount.to_integral_value():
        raise ValueError("Remittance rates must be whole toman")
    return f"{int(amount):,}".translate(PERSIAN_DIGITS)


def build_kiani_remittance_post(
    rates: dict[str, Decimal],
    *,
    now: datetime | None = None,
    order_handle: str = "@Kianiexchangebot",
    telegram_url: str = "https://t.me/TL905411603664",
    whatsapp_url: str = "https://wa.me/905392905686",
) -> str:
    """Format the separate seven-currency Kiani remittance-rate board.

    Rates must come from the existing remittance-rate source of truth.
    Do not substitute open-market or Kiani retail buy/sell quotes.
    This pure formatter does not fetch rates or select a channel.
    """
    missing = [code for code, _, _ in REMITTANCE_CURRENCIES if code not in rates]
    if missing:
        raise ValueError("Missing Kiani remittance rates: " + ", ".join(missing))
    local = (now or datetime.now(ISTANBUL_TZ)).astimezone(ISTANBUL_TZ)
    _, month, day = gregorian_to_jalali(
        local.year, local.month, local.day
    )
    weekday = PERSIAN_WEEKDAYS[local.weekday()]
    date_text = (
        f"{weekday} {day} {JALALI_MONTHS[month]}"
        .translate(PERSIAN_DIGITS)
    )
    time_text = local.strftime("%H:%M").translate(PERSIAN_DIGITS)
    lines = [
        "💸 <b>نرخ حواله به ایران</b>",
        f"📆 {date_text} · ⏰ {time_text}",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for code, flag, label in REMITTANCE_CURRENCIES:
        amount = _fmt_persian_toman(rates[code])
        lines.append(f"{flag} {label}　<code>{amount}</code>")
    telegram_link = html.escape(telegram_url, quote=True)
    whatsapp_link = html.escape(whatsapp_url, quote=True)
    lines.extend([
        "",
        "💰 نرخ‌ها به تومان است",
        "━━━━━━━━━━━━━━",
        f"📲 نرخ لحظه‌ای و سایر ارزها: {html.escape(order_handle)}",
        (
            f'✈️ <a href="{telegram_link}">تلگرام</a>'
            f'  |  💬 <a href="{whatsapp_link}">واتس‌اپ</a>'
        ),
    ])
    return "\n".join(lines)


def build_kiani_try_receive_post(
    rates: dict[str, Decimal],
    *,
    order_handle: str = "@Kianiexchangebot",
) -> str:
    """Show toman required when the customer wants to receive fixed TRY amounts."""
    buy_try = rates["buy_lira"]
    amounts = (Decimal("10000"), Decimal("50000"), Decimal("100000"))

    ltr = "\u200e"
    table = [ltr + f"{'TL':>10} {'TOMAN':>16}"]
    for try_amount in amounts:
        toman = try_amount * buy_try
        table.append(
            ltr + f"{_fmt_int(try_amount):>10} {_fmt_int(toman):>16}"
        )

    return "\n".join(
        [
            "🧮 <b>برای دریافت این مقدار لیر چند تومان باید واریز بشود؟</b>",
            "",
            "در ایران 🇮🇷 تومان واریز می کنید",
            "و معادل آن لیر ترکیه 🇹🇷 دریافت می کنید",
            "",
            "<pre>" + "\n".join(table) + "</pre>",
            "",
            f"بر اساس نرخ فروش فعلی: <b>{_fmt_int(buy_try)}</b> تومان",
            f"🤖 ثبت سفارش: {html.escape(order_handle)}",
        ]
    )


def build_kiani_toman_receive_post(
    rates: dict[str, Decimal],
    *,
    order_handle: str = "@Kianiexchangebot",
) -> str:
    """Show TRY required when the customer wants to receive fixed toman amounts."""
    sell_try = rates["sell_lira"]
    amounts = (
        Decimal("50000000"),
        Decimal("100000000"),
        Decimal("500000000"),
    )

    ltr = "\u200e"
    table = [ltr + f"{'TOMAN':>16} {'TL':>10}"]
    for toman in amounts:
        try_amount = toman / sell_try
        table.append(
            ltr + f"{_fmt_int(toman):>16} {_fmt_required_try(try_amount):>10}"
        )

    return "\n".join(
        [
            "🧮 <b>برای دریافت این مقدار تومان چند لیر باید واریز بشود؟</b>",
            "",
            "در ترکیه 🇹🇷 لیر واریز می کنید",
            "و معادل آن تومان در ایران 🇮🇷 دریافت می کنید",
            "",
            "<pre>" + "\n".join(table) + "</pre>",
            "",
            f"بر اساس نرخ خرید فعلی: <b>{_fmt_int(sell_try)}</b> تومان",
            f"🤖 ثبت سفارش: {html.escape(order_handle)}",
        ]
    )
