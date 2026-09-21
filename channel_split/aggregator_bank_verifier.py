#!/usr/bin/env python3
"""Independent third-party bank-rate verifiers.

These sources are deliberately grouped conservatively. A third-party website
does not automatically count as an independent source family merely because it
has a different domain. For Garanti BBVA we currently expose one external
aggregator family backed by CanliDoviz; additional aggregators may be used as
cross-checks later without inflating quorum until upstream independence is
established.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

CANLIDOVIZ_GARANTI_URL = (
    "https://canlidoviz.com/doviz-kurlari/garanti-bankasi"
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in {"td", "th"}:
            self._in_cell = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)
        if self._in_cell:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            value = " ".join("".join(self._parts).split())
            self._row.append(value)
            self._in_cell = False
            self._parts = []
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _decimal_from_cell(value: str) -> Decimal | None:
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)",
        value.replace("\xa0", " "),
    )
    if not match:
        return None
    token = match.group(1).replace(",", ".")
    try:
        parsed = Decimal(token)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _pair_code(pair: str) -> str:
    if pair == "USD/TRY":
        return "USD"
    if pair == "EUR/TRY":
        return "EUR"
    raise ValueError(f"Unsupported external Garanti pair: {pair}")


def _parse_page_timestamp(text: str) -> datetime | None:
    patterns = (
        r"PİYASA\s*:\s*(?:AÇIK|KAPALI)\s+"
        r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2})",
        r"PIYASA\s*:\s*(?:ACIK|KAPALI)\s+"
        r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        try:
            naive = datetime.strptime(match.group(1), "%d/%m/%Y %H:%M:%S")
        except ValueError:
            continue
        return naive.replace(tzinfo=ISTANBUL_TZ)
    return None


def _assert_fresh(
    updated: datetime | None,
    *,
    now: datetime | None = None,
    max_age_minutes: int = 720,
) -> None:
    if updated is None:
        raise ValueError("CanliDoviz page has no parseable update timestamp")

    current = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)
    age_seconds = (current - updated.astimezone(ISTANBUL_TZ)).total_seconds()

    if age_seconds < -300:
        raise ValueError("CanliDoviz timestamp is unexpectedly in the future")

    age_minutes = max(age_seconds, 0) / 60
    if age_minutes > max_age_minutes:
        raise ValueError(
            f"CanliDoviz Garanti data is stale: {age_minutes:.1f} minutes old "
            f"(limit {max_age_minutes})"
        )


def parse_canlidoviz_garanti_quote(
    html: str,
    pair: str,
    *,
    now: datetime | None = None,
    max_age_minutes: int = 720,
) -> tuple[Decimal, Decimal]:
    code = _pair_code(pair)
    parser = _TableParser()
    parser.feed(html)

    page_text = " ".join(parser.text_parts)
    _assert_fresh(
        _parse_page_timestamp(page_text),
        now=now,
        max_age_minutes=max_age_minutes,
    )

    row = next(
        (
            row
            for row in parser.rows
            if row
            and re.search(rf"\b{re.escape(code)}\b", row[0], re.IGNORECASE)
        ),
        None,
    )
    if row is None:
        raise ValueError(f"CanliDoviz Garanti page is missing {code}")

    numeric_cells: list[Decimal] = []
    for cell in row[1:]:
        parsed = _decimal_from_cell(cell)
        if parsed is not None:
            numeric_cells.append(parsed)
        if len(numeric_cells) >= 2:
            break

    if len(numeric_cells) < 2:
        raise ValueError(
            f"CanliDoviz Garanti {code} row has no usable buy/sell pair"
        )

    buy, sell = numeric_cells[0], numeric_cells[1]
    if sell <= buy:
        raise ValueError(
            f"CanliDoviz Garanti {code} quote is crossed: buy={buy} sell={sell}"
        )
    return buy, sell


def _fetch_html(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-BankConsensusVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(
            f"CanliDoviz verifier returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load CanliDoviz verifier: {exc}") from exc


def fetch_canlidoviz_garanti_quote(
    pair: str,
    *,
    timeout: int = 20,
    max_age_minutes: int = 720,
) -> tuple[Decimal, Decimal]:
    return parse_canlidoviz_garanti_quote(
        _fetch_html(CANLIDOVIZ_GARANTI_URL, timeout),
        pair,
        max_age_minutes=max_age_minutes,
    )
