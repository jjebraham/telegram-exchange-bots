#!/usr/bin/env python3
"""Fetch and format Turkish Kapalicarsi gold prices for AlanChande."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class GoldQuote:
    key: str
    fa_label: str
    url: str
    buy: Decimal
    sell: Decimal


ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

DISPLAY_GOLD_NAMES = {
    "gram": "GRAM",
    "quarter": "CEYREK",
    "half": "YARIM",
    "tam": "TAM",
}

GOLD_ASSETS = (
    (
        "gram",
        "گرم طلا",
        "https://altin.doviz.com/kapalicarsi/gram-altin",
    ),
    (
        "quarter",
        "ربع سکه",
        "https://altin.doviz.com/ceyrek-altin",
    ),
    (
        "half",
        "نیم سکه",
        "https://altin.doviz.com/yarim-altin",
    ),
    (
        "tam",
        "تمام سکه",
        "https://altin.doviz.com/tam-altin",
    ),
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


_NUMBER = r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d+"
_PAIR_RE = re.compile(rf"({_NUMBER})\s*/\s*({_NUMBER})")


def _tr_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Turkish decimal: {value!r}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"Invalid positive price: {value!r}")
    return result


def parse_buy_sell(html: str) -> tuple[Decimal, Decimal]:
    parser = _TextParser()
    parser.feed(html)

    for index, part in enumerate(parser.parts):
        if "Alış / Satış" not in part:
            continue
        window = " ".join(parser.parts[index : index + 12])
        match = _PAIR_RE.search(window)
        if match:
            return _tr_decimal(match.group(1)), _tr_decimal(match.group(2))

    raise ValueError("Gold source did not expose an Alış / Satış pair")


def fetch_gold_quote(
    key: str,
    fa_label: str,
    url: str,
    timeout: int = 20,
) -> GoldQuote:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            "User-Agent": "AlanChande-GoldPublisher/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Gold source {key} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load gold source {key}: {exc}") from exc

    buy, sell = parse_buy_sell(html)
    return GoldQuote(key=key, fa_label=fa_label, url=url, buy=buy, sell=sell)


def fetch_turkish_gold_quotes(timeout: int = 20) -> list[GoldQuote]:
    return [
        fetch_gold_quote(key, fa_label, url, timeout=timeout)
        for key, fa_label, url in GOLD_ASSETS
    ]


def _fmt_tl(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")


def build_turkish_gold_post(quotes: list[GoldQuote]) -> str:
    if not quotes:
        raise ValueError("No gold quotes supplied")

    table_lines = [
        f"🌕{'GOLD':<8} {'SELL':>9} {'BUY':>9}",
    ]
    for quote in quotes:
        table_lines.append(
            f"🌕{DISPLAY_GOLD_NAMES.get(quote.key, quote.key):<8} "
            f"{_fmt_tl(quote.sell):>9} "
            f"{_fmt_tl(quote.buy):>9}"
        )

    lines = [
        "🥇 <b>قیمت طلای ترکیه  | Kapalıçarşı</b>",
        "",
        "🔴 SELL = فروش　•　🟢 BUY = خرید",
        "",
        "<pre>" + "\n".join(table_lines) + "</pre>",
        "",
        "💵 واحد: لیر ترکیه 🇹🇷",
        f"🕒 <code>{datetime.now(ISTANBUL_TZ).strftime('%H:%M')}</code> استانبول",
        "قیمت‌ها صرفاً جهت اطلاع‌رسانی است.",
    ]
    return "\n".join(lines)
