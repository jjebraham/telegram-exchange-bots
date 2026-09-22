#!/usr/bin/env python3
"""Customer-facing Kiani Exchange Telegram post formatters."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
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
            "🇹🇷 <b>نرخ لیر ترکیه</b>",
            "",
            "<pre>",
            f"💸 BUY   TL {_fmt_int(buy_from_us)} = خرید لیر از ما",
            f"💵 SELL  TL {_fmt_int(sell_to_us)} = فروش لیر به ما",
            "</pre>",
            "",
            "⚠️ <b>لطفاً قبل از واریز هماهنگ کنید:</b>",
            f'🔹 تلگرام: <a href="{telegram_link}">{telegram_link}</a>',
            f'🔹 واتس‌اپ: <a href="{whatsapp_link}">{whatsapp_link}</a>',
            "",
            "💵 واحد: تومان 🇮🇷",
        ]
    )
