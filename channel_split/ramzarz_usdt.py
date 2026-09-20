#!/usr/bin/env python3
"""Ramzarz.news USDT exchange-price fallback adapter.

Source page:
https://ramzarz.news/coins/tether/

The Iranian exchange table exposes:
- فروش به کاربر = exchange sells to customer = customer BUY price
- خرید از کاربر = exchange buys from customer = customer SELL price
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RAMZARZ_USDT_URL = "https://ramzarz.news/coins/tether/"

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ramzinex", "رمزینکس"), "رمزینکس"),
    (("wallex", "والکس"), "والکس"),
    (("nobitex", "نوبیتکس"), "نوبیتکس"),
    (("tabdeal", "تبدیل"), "تبدیل"),
)


@dataclass(frozen=True)
class RamzarzUsdtQuote:
    exchange: str
    buy_toman: Decimal
    sell_toman: Decimal


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
            value = " ".join("".join(self._parts).split())
            self._row.append(value)
            self._parts = []
            self._in_cell = False
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _parse_toman(value: str) -> Decimal:
    normalized = value.translate(_DIGITS)
    normalized = normalized.replace(",", "").replace("٬", "").replace(" ", "")
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", normalized)
    if not match:
        raise ValueError(f"No Toman number in {value!r}")
    try:
        number = Decimal(match.group(0))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid Toman number in {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"Invalid Toman value in {value!r}")
    return number


def _canonical_exchange(text: str) -> str | None:
    lowered = text.lower()
    for aliases, canonical in ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            return canonical
    return None


def parse_ramzarz_usdt_html(html: str) -> list[RamzarzUsdtQuote]:
    parser = _TableParser()
    parser.feed(html)

    quotes: list[RamzarzUsdtQuote] = []
    seen: set[str] = set()

    for row in parser.rows:
        if len(row) < 3:
            continue

        exchange = _canonical_exchange(row[0])
        if exchange is None or exchange in seen:
            continue

        try:
            buy_toman = _parse_toman(row[1])
            sell_toman = _parse_toman(row[2])
        except ValueError:
            continue

        if sell_toman >= buy_toman:
            continue

        quotes.append(
            RamzarzUsdtQuote(
                exchange=exchange,
                buy_toman=buy_toman,
                sell_toman=sell_toman,
            )
        )
        seen.add(exchange)

    if not quotes:
        raise ValueError("Ramzarz USDT page did not expose exchange rows")
    return quotes


def fetch_ramzarz_usdt_quotes(
    url: str = RAMZARZ_USDT_URL,
    timeout: int = 15,
) -> list[RamzarzUsdtQuote]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
            "User-Agent": "AlanChande-RamzarzFallback/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Ramzarz USDT source returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load Ramzarz USDT source: {exc}") from exc

    return parse_ramzarz_usdt_html(html)
