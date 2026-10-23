#!/usr/bin/env python3
"""Fetch and format USDT prices across Iranian crypto exchanges for AlanChande.

MVP source: TGJU's USDT comparison table. TGJU publishes values in Iranian
rials; the Telegram post converts them to toman.

Safety filters:
- require a timestamp no more than 90 minutes old (or 5 minutes in the future);
- keep rows from the modal (most common) source date;
- keep rows no more than 90 minutes behind the freshest row on that date;
- reject sell-price outliers more than 12% away from the median;
- ignore zero/missing sell prices.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
import statistics
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TGJU_USDT_URL = "https://www.tgju.org/crypto/exchanges/local/asset/usdt"

PREFERRED_EXCHANGES = (
    "والکس",
    "نوبیتکس",
    "رمزینکس",
    "بیت پین",
    "آبان تتر",
    "تبدیل",
    "تترلند",
    "اکسیر",
)

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _jalali_to_gregorian(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Convert a Jalali calendar date to Gregorian (no optional deps)."""
    jy = year - 979
    days = 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4)
    days += (month - 1) * 31 if month <= 7 else 186 + (month - 7) * 30
    days += day - 1 + 79
    gy = 1600 + 400 * (days // 146097)
    days %= 146097
    leap = True
    if days >= 36525:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
        else:
            leap = False
    gy += 4 * (days // 1461)
    days %= 1461
    if days >= 366:
        leap = False
        days -= 1
        gy += days // 365
        days %= 365
    month_lengths = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    gm = 1
    for length in month_lengths:
        if days < length:
            break
        days -= length
        gm += 1
    return gy, gm, days + 1


def _source_datetime(quote: UsdtExchangeQuote) -> datetime | None:
    if not quote.source_date or not quote.source_time:
        return None
    try:
        year, month, day = (int(part) for part in quote.source_date.split("/"))
        hour, minute = (int(part) for part in quote.source_time.split(":"))
        gy, gm, gd = _jalali_to_gregorian(year, month, day)
        return datetime(gy, gm, gd, hour, minute, tzinfo=TEHRAN_TZ)
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class UsdtExchangeQuote:
    exchange: str
    sell_rial: Decimal
    buy_rial: Decimal | None
    change_pct: Decimal | None
    source_date: str | None
    source_time: str | None

    @property
    def sell_toman(self) -> Decimal:
        return self.sell_rial / Decimal("10")

    @property
    def buy_toman(self) -> Decimal | None:
        return None if self.buy_rial is None else self.buy_rial / Decimal("10")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
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


def _parse_number(value: str, *, allow_zero: bool = False) -> Decimal:
    normalized = _ascii_digits(value)
    normalized = normalized.replace(",", "").replace("٬", "").replace(" ", "")
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", normalized)
    if not match:
        raise ValueError(f"No numeric value in {value!r}")
    try:
        number = Decimal(match.group(0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"Invalid value: {value!r}")
    return number


def _parse_change_pct(value: str) -> Decimal | None:
    normalized = _ascii_digits(value)
    match = re.search(r"\((-?[0-9]+(?:\.[0-9]+)?)%\)", normalized)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def _parse_timestamp(value: str) -> tuple[str | None, str | None]:
    normalized = _ascii_digits(value)
    match = re.search(r"(\d{4}/\d{2}/\d{2})\s*-\s*(\d{1,2}:\d{2})", normalized)
    if not match:
        return None, None
    hour, minute = match.group(2).split(":", 1)
    return match.group(1), f"{int(hour):02d}:{minute}"


def parse_usdt_comparison_html(html: str) -> list[UsdtExchangeQuote]:
    parser = _TableParser()
    parser.feed(html)

    quotes: list[UsdtExchangeQuote] = []
    seen: set[str] = set()

    for row in parser.rows:
        # Expected columns:
        # exchange | sell | buy | change | high | low | time | ...
        if len(row) < 7:
            continue
        exchange = row[0].strip()
        if not exchange or exchange in seen:
            continue

        try:
            sell = _parse_number(row[1])
        except ValueError:
            continue

        try:
            buy_raw = _parse_number(row[2], allow_zero=True)
            buy = buy_raw if buy_raw > 0 else None
        except ValueError:
            buy = None

        source_date, source_time = _parse_timestamp(row[6])
        quotes.append(
            UsdtExchangeQuote(
                exchange=exchange,
                sell_rial=sell,
                buy_rial=buy,
                change_pct=_parse_change_pct(row[3]),
                source_date=source_date,
                source_time=source_time,
            )
        )
        seen.add(exchange)

    if not quotes:
        raise ValueError("TGJU USDT source did not expose exchange rows")
    return quotes


def fetch_usdt_exchange_quotes(
    url: str = TGJU_USDT_URL,
    timeout: int = 25,
) -> list[UsdtExchangeQuote]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
            "User-Agent": "AlanChande-USDTComparison/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"TGJU USDT source returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load TGJU USDT source: {exc}") from exc

    return parse_usdt_comparison_html(html)


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def filter_usdt_quotes(
    quotes: list[UsdtExchangeQuote],
    *,
    max_lag_minutes: int = 90,
    max_median_deviation: Decimal = Decimal("0.12"),
    now: datetime | None = None,
) -> list[UsdtExchangeQuote]:
    if not quotes:
        return []

    current = now or datetime.now(TEHRAN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TEHRAN_TZ)
    else:
        current = current.astimezone(TEHRAN_TZ)
    cutoff = current - timedelta(minutes=max_lag_minutes)
    # TGJU can serve an old comparison-table snapshot while all rows still
    # agree with one another. Require an absolute, current timestamp too.
    quotes = [
        q
        for q in quotes
        if (stamp := _source_datetime(q)) is not None
        and cutoff <= stamp <= current + timedelta(minutes=5)
    ]
    if not quotes:
        return []

    dated = [q for q in quotes if q.source_date]
    modal_date: str | None = None
    if dated:
        modal_date = Counter(q.source_date for q in dated).most_common(1)[0][0]

    same_date = [
        q for q in quotes
        if modal_date is None or q.source_date is None or q.source_date == modal_date
    ]

    timed = [q for q in same_date if q.source_time]
    if timed:
        freshest = max(_minutes(q.source_time or "00:00") for q in timed)
        same_date = [
            q for q in same_date
            if q.source_time is None
            or freshest - _minutes(q.source_time) <= max_lag_minutes
        ]

    if not same_date:
        return []

    median = Decimal(str(statistics.median([float(q.sell_rial) for q in same_date])))
    if median <= 0:
        return same_date

    lower = median * (Decimal("1") - max_median_deviation)
    upper = median * (Decimal("1") + max_median_deviation)
    return [q for q in same_date if lower <= q.sell_rial <= upper]


def select_preferred_quotes(
    quotes: list[UsdtExchangeQuote],
    preferred: tuple[str, ...] = PREFERRED_EXCHANGES,
) -> list[UsdtExchangeQuote]:
    filtered = filter_usdt_quotes(quotes)
    by_name = {q.exchange: q for q in filtered}
    selected = [by_name[name] for name in preferred if name in by_name]
    if len(selected) < 4:
        raise ValueError(
            f"Only {len(selected)} preferred USDT exchanges survived freshness/outlier filtering"
        )
    return selected


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    rounded = value.quantize(Decimal("0.01"))
    arrow = "🔼" if rounded > 0 else "🔻" if rounded < 0 else "⚪️"
    return f" {arrow} <code>{abs(rounded):.2f}%</code>"


def build_usdt_exchange_post(quotes: list[UsdtExchangeQuote]) -> str:
    selected = select_preferred_quotes(quotes)
    average = sum((q.sell_toman for q in selected), Decimal("0")) / Decimal(len(selected))
    latest_times = [q.source_time for q in selected if q.source_time]
    latest_time = max(latest_times) if latest_times else None

    number_emojis = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣")
    lines = [
        "💎 <b>قیمت تتر در صرافی‌های ایران</b>",
        "",
        "💵 قیمت فروش صرافی به شما <i>(تومان)</i>",
        "",
    ]

    for idx, quote in enumerate(selected):
        lines.append(
            f"{number_emojis[idx]} <b>{quote.exchange}</b>　"
            f"<code>{_fmt_toman(quote.sell_toman)}</code>"
            f"{_fmt_pct(quote.change_pct)}"
        )

    lines.extend(
        [
            "",
            f"➗ <b>میانگین</b>　<code>{_fmt_toman(average)}</code> تومان",
        ]
    )
    if latest_time:
        lines.append(f"🕒 آخرین بروزرسانی منبع: <code>{latest_time}</code>")
    return "\n".join(lines)
