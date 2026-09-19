#!/usr/bin/env python3
"""Fetch and format Iran gold/coin market data for AlanChande.

MVP source: TGJU home page. Values published by TGJU are in Iranian rials;
the Telegram post converts them to toman.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TGJU_HOME_URL = "https://www.tgju.org/home"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

COIN_LABELS = (
    "سکه امامی",
    "سکه بهار آزادی",
    "نیم سکه",
    "ربع سکه",
    "سکه گرمی",
)

BUBBLE_LABELS = (
    "حباب سکه امامی",
    "حباب سکه بهار آزادی",
    "حباب نیم سکه",
    "حباب ربع سکه",
    "حباب سکه گرمی",
)

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


@dataclass(frozen=True)
class IranGoldMarket:
    coin_prices_rial: dict[str, Decimal]
    bubble_values_rial: dict[str, Decimal]
    gold18_rial: Decimal | None = None
    mesghal_rial: Decimal | None = None


class _TGJUParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.text_parts.append(clean)
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            value = " ".join("".join(self._cell_parts).split())
            self._row.append(value)
            self._in_cell = False
            self._cell_parts = []
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _ascii_digits(value: str) -> str:
    return value.translate(_DIGITS)


def _parse_positive_number(value: str) -> Decimal:
    cleaned = _ascii_digits(value)
    cleaned = cleaned.replace(",", "").replace("٬", "").replace(" ", "")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if not cleaned:
        raise ValueError(f"No numeric value in {value!r}")
    try:
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"Invalid positive value: {value!r}")
    return number


def _first_row_values(rows: list[list[str]], labels: tuple[str, ...]) -> dict[str, Decimal]:
    found: dict[str, Decimal] = {}
    for row in rows:
        if len(row) < 2:
            continue
        label = row[0].strip()
        if label not in labels or label in found:
            continue
        for cell in row[1:]:
            try:
                found[label] = _parse_positive_number(cell)
                break
            except ValueError:
                continue
    return found


def _extract_summary_value(text: str, labels: tuple[str, ...]) -> Decimal | None:
    normalized = _ascii_digits(text)
    for label in labels:
        # TGJU's top summary normally renders as: "طلا ۱۸ 235,013,000 ..."
        match = re.search(rf"{re.escape(label)}\s+([0-9][0-9,٬]*)", normalized)
        if match:
            try:
                return _parse_positive_number(match.group(1))
            except ValueError:
                pass
    return None


def parse_tgju_home(html: str) -> IranGoldMarket:
    parser = _TGJUParser()
    parser.feed(html)

    coins = _first_row_values(parser.rows, COIN_LABELS)
    bubbles = _first_row_values(parser.rows, BUBBLE_LABELS)

    missing_coins = [name for name in COIN_LABELS if name not in coins]
    missing_bubbles = [name for name in BUBBLE_LABELS if name not in bubbles]
    if missing_coins:
        raise ValueError("TGJU source is missing coin rows: " + ", ".join(missing_coins))
    if missing_bubbles:
        raise ValueError("TGJU source is missing bubble rows: " + ", ".join(missing_bubbles))

    text = " ".join(parser.text_parts)
    gold18 = _extract_summary_value(text, ("طلا ۱۸", "طلا 18", "طلای 18 عیار", "طلای ۱۸ عیار"))
    mesghal = _extract_summary_value(text, ("مثقال طلا", "مثقال طلای 18", "مثقال طلای ۱۸"))

    return IranGoldMarket(
        coin_prices_rial=coins,
        bubble_values_rial=bubbles,
        gold18_rial=gold18,
        mesghal_rial=mesghal,
    )


def fetch_iran_gold_market(url: str = TGJU_HOME_URL, timeout: int = 25) -> IranGoldMarket:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
            "User-Agent": "AlanChande-IranGoldPublisher/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"TGJU returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load TGJU: {exc}") from exc

    return parse_tgju_home(html)


def _toman(rial: Decimal) -> Decimal:
    return rial / Decimal("10")


def _fmt_toman(rial: Decimal) -> str:
    return f"{int(_toman(rial).quantize(Decimal('1'))):,}"


def _bubble_pct(bubble_rial: Decimal, price_rial: Decimal) -> str:
    pct = (bubble_rial / price_rial) * Decimal("100")
    return f"{pct.quantize(Decimal('0.01')):.2f}".rstrip("0").rstrip(".")


def build_iran_gold_post(market: IranGoldMarket) -> str:
    now = datetime.now(TEHRAN_TZ).strftime("%H:%M")
    prices = market.coin_prices_rial
    bubbles = market.bubble_values_rial

    lines = [
        "🪙 <b>طلا و سکه ایران</b>",
        "",
        "💰 <b>قیمت بازار</b> <i>(تومان)</i>",
        "",
        f"🌕 <b>سکه امامی</b>　<code>{_fmt_toman(prices['سکه امامی'])}</code>",
        f"🌕 <b>سکه بهار آزادی</b>　<code>{_fmt_toman(prices['سکه بهار آزادی'])}</code>",
        f"🟡 <b>نیم سکه</b>　<code>{_fmt_toman(prices['نیم سکه'])}</code>",
        f"🟡 <b>ربع سکه</b>　<code>{_fmt_toman(prices['ربع سکه'])}</code>",
        f"🪙 <b>سکه گرمی</b>　<code>{_fmt_toman(prices['سکه گرمی'])}</code>",
    ]

    if market.gold18_rial is not None or market.mesghal_rial is not None:
        lines.extend(["", "✨ <b>طلا</b>", ""])
        if market.gold18_rial is not None:
            lines.append(f"✨ <b>گرم طلای ۱۸ عیار</b>　<code>{_fmt_toman(market.gold18_rial)}</code>")
        if market.mesghal_rial is not None:
            lines.append(f"⚖️ <b>مثقال طلا</b>　<code>{_fmt_toman(market.mesghal_rial)}</code>")

    lines.extend(["", "🎈 <b>حباب سکه</b>", ""])

    bubble_to_coin = (
        ("🌕", "امامی", "حباب سکه امامی", "سکه امامی"),
        ("🌕", "بهار آزادی", "حباب سکه بهار آزادی", "سکه بهار آزادی"),
        ("🟡", "نیم سکه", "حباب نیم سکه", "نیم سکه"),
        ("🟡", "ربع سکه", "حباب ربع سکه", "ربع سکه"),
        ("🪙", "سکه گرمی", "حباب سکه گرمی", "سکه گرمی"),
    )

    for emoji, label, bubble_key, coin_key in bubble_to_coin:
        lines.append(
            f"{emoji} <b>{label}</b>　"
            f"<code>{_fmt_toman(bubbles[bubble_key])}</code> تومان　"
            f"<code>{_bubble_pct(bubbles[bubble_key], prices[coin_key])}%</code>"
        )

    lines.extend(["", f"🕒 بروزرسانی تهران: <code>{now}</code>"])
    return "\n".join(lines)
