#!/usr/bin/env python3
"""Iran open-market currency board for AlanChande.

Primary source: TGJU free-market currency table. TGJU publishes these values in
Iranian rials; this module normalizes them to toman for the public post.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TGJU_CURRENCY_URL = "https://www.tgju.org/currency"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# code, flag, public Persian name, accepted TGJU labels
CURRENCY_ROWS = (
    ("USD", "🇺🇸", "دلار آمریکا", ("دلار", "دلار آمریکا")),
    ("EUR", "🇪🇺", "یورو", ("یورو",)),
    ("GBP", "🇬🇧", "پوند انگلیس", ("پوند انگلیس", "پوند")),
    ("CHF", "🇨🇭", "فرانک سوئیس", ("فرانک سوئیس", "فرانک سوییس")),
    ("CAD", "🇨🇦", "دلار کانادا", ("دلار کانادا",)),
    ("AUD", "🇦🇺", "دلار استرالیا", ("دلار استرالیا",)),
    ("SEK", "🇸🇪", "کرون سوئد", ("کرون سوئد",)),
    ("NOK", "🇳🇴", "کرون نروژ", ("کرون نروژ",)),
    ("RUB", "🇷🇺", "روبل روسیه", ("روبل روسیه", "روبل")),
    ("THB", "🇹🇭", "بات تایلند", ("بات تایلند", "بت تایلند")),
    ("SGD", "🇸🇬", "دلار سنگاپور", ("دلار سنگاپور",)),
    ("HKD", "🇭🇰", "دلار هنگ کنگ", ("دلار هنگ کنگ",)),
    ("AZN", "🇦🇿", "منات آذربایجان", ("منات آذربایجان",)),
    ("DKK", "🇩🇰", "کرون دانمارک", ("کرون دانمارک",)),
    ("AED", "🇦🇪", "درهم امارات", ("درهم امارات",)),
    ("TRY", "🇹🇷", "لیر ترکیه", ("لیر ترکیه",)),
    ("CNY", "🇨🇳", "یوان چین", ("یوان چین",)),
    ("SAR", "🇸🇦", "ریال عربستان", ("ریال عربستان",)),
    ("INR", "🇮🇳", "روپیه هند", ("روپیه هند",)),
    ("MYR", "🇲🇾", "رینگیت مالزی", ("رینگیت مالزی",)),
    ("AFN", "🇦🇫", "افغانی افغانستان", ("افغانی", "افغانی افغانستان")),
    ("KWD", "🇰🇼", "دینار کویت", ("دینار کویت",)),
    ("BHD", "🇧🇭", "دینار بحرین", ("دینار بحرین",)),
    ("OMR", "🇴🇲", "ریال عمان", ("ریال عمان",)),
    ("QAR", "🇶🇦", "ریال قطر", ("ریال قطر",)),
)

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in {"td", "th"}:
            self._in_cell = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join("".join(self._parts).split()))
            self._in_cell = False
            self._parts = []
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _normalize_label(value: str) -> str:
    return (
        " ".join(value.replace("\u200c", " ").split())
        .replace("ي", "ی")
        .replace("ك", "ک")
        .strip()
    )


def _parse_positive_number(value: str) -> Decimal:
    text = value.translate(_DIGITS).replace(",", "").replace("٬", "")
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", text)
    if not match:
        raise ValueError(f"No numeric rate in {value!r}")
    try:
        number = Decimal(match.group(0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid rate in {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"Rate must be positive: {value!r}")
    return number


def parse_tgju_currency_page(html: str) -> dict[str, Decimal]:
    """Parse the free-market TGJU table and return toman values by ISO code."""
    parser = _TableParser()
    parser.feed(html)

    label_to_code: dict[str, str] = {}
    for code, _flag, _name, labels in CURRENCY_ROWS:
        for label in labels:
            label_to_code[_normalize_label(label)] = code

    rates_rial: dict[str, Decimal] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        code = label_to_code.get(_normalize_label(row[0]))
        if code is None or code in rates_rial:
            continue
        try:
            rates_rial[code] = _parse_positive_number(row[1])
        except ValueError:
            continue

    required = [code for code, *_rest in CURRENCY_ROWS]
    missing = [code for code in required if code not in rates_rial]
    if missing:
        raise ValueError(
            "TGJU free-market currency table is missing required rows: "
            + ", ".join(missing)
        )

    # TGJU publishes the Iran-market table in rial. Public AlanChande values are
    # intentionally normalized to toman.
    return {code: value / Decimal("10") for code, value in rates_rial.items()}


def fetch_iran_open_market_fx(
    url: str = TGJU_CURRENCY_URL,
    timeout: int = 25,
) -> dict[str, Decimal]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-IranFxPublisher/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"TGJU currency source returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load TGJU currency source: {exc}") from exc

    return parse_tgju_currency_page(html)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    rounded = value.quantize(Decimal("0.01"))
    if rounded > 0:
        return f"+{rounded:.2f}%"
    if rounded < 0:
        return f"-{abs(rounded):.2f}%"
    return "0.00%"


def build_iran_fx_post(
    rates_toman: dict[str, Decimal],
    change_24h: Mapping[str, Decimal] | None = None,
    change_1m: Mapping[str, Decimal] | None = None,
) -> str:
    missing = [code for code, *_rest in CURRENCY_ROWS if code not in rates_toman]
    if missing:
        raise ValueError("Iran FX post is missing: " + ", ".join(missing))

    change_24h = change_24h or {}
    change_1m = change_1m or {}

    table = [f"{'CURRENCY':<8} {'TOMAN':>10} {'Δ24H':>8} {'Δ1M':>8}"]
    for code, flag, _name, _labels in CURRENCY_ROWS:
        table.append(
            f"{flag} {code:<3} "
            f"{_fmt_toman(rates_toman[code]):>10} "
            f"{_fmt_pct(change_24h.get(code)):>8} "
            f"{_fmt_pct(change_1m.get(code)):>8}"
        )

    now = datetime.now(TEHRAN_TZ).strftime("%H:%M")
    return "\n".join(
        [
            "💱 <b>نرخ ارز آزاد ایران</b>",
            "",
            "<pre>" + "\n".join(table) + "</pre>",
            "",
            "💵 واحد: تومان 🇮🇷",
            f"🕒 <code>{now}</code> تهران",
            "نرخ‌ها مربوط به بازار آزاد و صرفاً جهت اطلاع‌رسانی هستند.",
        ]
    )
