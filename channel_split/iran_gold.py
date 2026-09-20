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


def _parse_number(value: str, *, allow_negative: bool = False) -> Decimal:
    cleaned = _ascii_digits(value)
    cleaned = cleaned.replace(",", "").replace("٬", "").replace(" ", "")
    pattern = r"-?[0-9]+(?:\.[0-9]+)?" if allow_negative else r"[0-9]+(?:\.[0-9]+)?"
    match = re.search(pattern, cleaned)
    if not match:
        raise ValueError(f"No numeric value in {value!r}")
    try:
        number = Decimal(match.group(0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if not number.is_finite() or (not allow_negative and number <= 0):
        raise ValueError(f"Invalid numeric value: {value!r}")
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
                found[label] = _parse_number(cell)
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
                return _parse_number(match.group(1))
            except ValueError:
                pass
    return None


def parse_tgju_home(html: str) -> IranGoldMarket:
    parser = _TGJUParser()
    parser.feed(html)

    coins = _first_row_values(parser.rows, COIN_LABELS)

    bubbles: dict[str, Decimal] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        label = row[0].strip()
        if label not in BUBBLE_LABELS or label in bubbles:
            continue
        try:
            bubbles[label] = _parse_number(row[1], allow_negative=True)
        except ValueError:
            continue

    missing_coins = [name for name in COIN_LABELS if name not in coins]
    missing_bubbles = [name for name in BUBBLE_LABELS if name not in bubbles]
    if missing_coins:
        raise ValueError("TGJU source is missing coin rows: " + ", ".join(missing_coins))
    if missing_bubbles:
        raise ValueError("TGJU source is missing bubble rows: " + ", ".join(missing_bubbles))

    gold_rows = _first_row_values(
        parser.rows,
        ("طلای 18 عیار", "طلای ۱۸ عیار", "طلا 18", "طلا ۱۸"),
    )
    mesghal_rows = _first_row_values(
        parser.rows,
        ("مثقال طلا", "مثقال طلای 18", "مثقال طلای ۱۸"),
    )

    text = " ".join(parser.text_parts)
    gold18 = next(iter(gold_rows.values()), None)
    if gold18 is None:
        gold18 = _extract_summary_value(text, ("طلا ۱۸", "طلا 18", "طلای 18 عیار", "طلای ۱۸ عیار"))

    mesghal = next(iter(mesghal_rows.values()), None)
    if mesghal is None:
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


def _fmt_signed_toman(rial: Decimal) -> str:
    value = int(_toman(rial).quantize(Decimal("1")))
    return f"{value:,}"


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
        lines.extend(["", "✨ <b>طلا</b>"])
        if market.gold18_rial is not None:
            lines.append(
                f"✨ <b>طلای ۱۸ عیار</b>　<code>{_fmt_toman(market.gold18_rial)}</code>"
            )
        if market.mesghal_rial is not None:
            lines.append(
                f"⚖️ <b>مثقال طلا</b>　<code>{_fmt_toman(market.mesghal_rial)}</code>"
            )

    lines.extend(
        [
            "",
            "🎈 <b>حباب سکه</b>",
            f"🌕 امامی　<code>{_fmt_signed_toman(bubbles['حباب سکه امامی'])}</code>　"
            f"<code>{_bubble_pct(bubbles['حباب سکه امامی'], prices['سکه امامی'])}%</code>",
            f"🌕 بهار آزادی　<code>{_fmt_signed_toman(bubbles['حباب سکه بهار آزادی'])}</code>　"
            f"<code>{_bubble_pct(bubbles['حباب سکه بهار آزادی'], prices['سکه بهار آزادی'])}%</code>",
            f"🟡 نیم سکه　<code>{_fmt_signed_toman(bubbles['حباب نیم سکه'])}</code>　"
            f"<code>{_bubble_pct(bubbles['حباب نیم سکه'], prices['نیم سکه'])}%</code>",
            f"🟡 ربع سکه　<code>{_fmt_signed_toman(bubbles['حباب ربع سکه'])}</code>　"
            f"<code>{_bubble_pct(bubbles['حباب ربع سکه'], prices['ربع سکه'])}%</code>",
            f"🪙 سکه گرمی　<code>{_fmt_signed_toman(bubbles['حباب سکه گرمی'])}</code>　"
            f"<code>{_bubble_pct(bubbles['حباب سکه گرمی'], prices['سکه گرمی'])}%</code>",
            "",
            f"🕒 <code>{now}</code> تهران",
            "قیمت‌ها صرفاً جهت اطلاع‌رسانی است.",
        ]
    )
    return "\n".join(lines)
