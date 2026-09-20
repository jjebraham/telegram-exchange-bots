#!/usr/bin/env python3
"""Fetch and format Turkish FX bank comparisons for AlanChande.

MVP data source
---------------
The implementation uses the public server-rendered comparison tables on
kur.doviz.com. One request contains Kapalicarsi plus the Turkish bank rows we
need, so USD/TRY and EUR/TRY can share the same parser and formatter.

The module is intentionally provider-shaped: once official endpoints/keys are
available, each bank can be replaced without changing the Telegram formatter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

USD_COMPARISON_URL = "https://kur.doviz.com/kapalicarsi/amerikan-dolari"
EUR_COMPARISON_URL = "https://kur.doviz.com/kapalicarsi/euro"
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

DISPLAY_NAMES = {
    "Kapalıçarşı": "KAPALI",
    "Garanti BBVA": "GARANTI",
    "İş Bankası": "ISBANK",
    "Kuveyt Türk": "KUVEYT",
    "Ziraat Bankası": "ZIRAAT",
}

TARGETS = (
    "Kapalıçarşı",
    "Garanti BBVA",
    "İş Bankası",
    "Kuveyt Türk",
    "Ziraat Bankası",
)


@dataclass(frozen=True)
class BankQuote:
    name: str
    buy: Decimal
    sell: Decimal

    @property
    def spread(self) -> Decimal:
        return self.sell - self.buy


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


def _tr_decimal(value: str) -> Decimal:
    # Turkish display: 48,6900 or 1.234,5600
    cleaned = value.strip().replace(".", "").replace(",", ".")
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Turkish decimal: {value!r}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"Invalid positive rate: {value!r}")
    return result


def parse_comparison_html(html: str, targets: Iterable[str] = TARGETS) -> list[BankQuote]:
    wanted = tuple(targets)
    parser = _TableParser()
    parser.feed(html)

    found: dict[str, BankQuote] = {}
    for row in parser.rows:
        if len(row) < 3:
            continue
        name = row[0].strip()
        if name not in wanted or name in found:
            continue
        try:
            found[name] = BankQuote(name=name, buy=_tr_decimal(row[1]), sell=_tr_decimal(row[2]))
        except ValueError:
            continue

    missing = [name for name in wanted if name not in found]
    if missing:
        raise ValueError("Bank comparison source is missing rows: " + ", ".join(missing))
    return [found[name] for name in wanted]


def _fetch_comparison(url: str, timeout: int = 20) -> list[BankQuote]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            "User-Agent": "AlanChande-MarketPublisher/1.2",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Bank comparison source returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load bank comparison source: {exc}") from exc
    return parse_comparison_html(html)


def fetch_usd_comparison(url: str = USD_COMPARISON_URL, timeout: int = 20) -> list[BankQuote]:
    return _fetch_comparison(url, timeout)


def fetch_eur_comparison(url: str = EUR_COMPARISON_URL, timeout: int = 20) -> list[BankQuote]:
    return _fetch_comparison(url, timeout)


def _fmt(value: Decimal) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _fmt_table(value: Decimal) -> str:
    return f"{value:.4f}"


def _build_comparison_post(quotes: list[BankQuote], *, title: str, pair: str) -> str:
    if not quotes:
        raise ValueError("No bank quotes supplied")

    cheapest_buy = min(quotes, key=lambda q: q.sell)
    highest_sell = max(quotes, key=lambda q: q.buy)

    table_lines = [
        f"{'MARKET':<8} {'SELL':>8} {'BUY':>8}",
    ]
    for q in quotes:
        table_lines.append(
            f"{DISPLAY_NAMES.get(q.name, q.name):<8} "
            f"{_fmt_table(q.sell):>8} "
            f"{_fmt_table(q.buy):>8}"
        )

    lines = [
        f"🏦 <b>{title}</b>",
        "",
        f"💱 <b>{pair}</b>",
        "🔴 SELL = فروش　•　🟢 BUY = خرید",
        "",
        "<pre>" + "\n".join(table_lines) + "</pre>",
        "",
        f"🛒 کمترین قیمت خرید: <b>{cheapest_buy.name}</b>　"
        f"<code>{_fmt(cheapest_buy.sell)}</code>",
        f"💰 بیشترین قیمت فروش: <b>{highest_sell.name}</b>　"
        f"<code>{_fmt(highest_sell.buy)}</code>",
        "",
        f"🕒 <code>{datetime.now(ISTANBUL_TZ).strftime('%H:%M')}</code> استانبول",
        "قیمت‌ها صرفاً جهت اطلاع‌رسانی است.",
    ]

    return "\n".join(lines)


def build_usd_comparison_post(quotes: list[BankQuote]) -> str:
    return _build_comparison_post(quotes, title="مقایسه نرخ دلار در ترکیه", pair="USD/TRY")


def build_eur_comparison_post(quotes: list[BankQuote]) -> str:
    return _build_comparison_post(quotes, title="مقایسه نرخ یورو در ترکیه", pair="EUR/TRY")
