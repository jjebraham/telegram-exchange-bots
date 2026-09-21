#!/usr/bin/env python3
"""Official-bank verification for selected Turkey bank FX rows."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ISBANK_URL = "https://www.isbank.com.tr/doviz-kurlari"
ZIRAAT_URL = "https://www.ziraatbank.com.tr/tr/fiyatlar-ve-oranlar"


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
            self._in_cell = False
            self._parts = []
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _number(value: str) -> Decimal | None:
    cleaned = value.strip().replace("\xa0", " ")
    match = re.search(r"(?<!\d)(\d{1,3}(?:[.]\d{3})*(?:,\d+)?|\d+(?:,\d+)?)(?!\d)", cleaned)
    if not match:
        return None
    token = match.group(1).replace(".", "").replace(",", ".")
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
    raise ValueError(f"Unsupported official bank pair: {pair}")


def _candidate_quotes(html: str, pair: str) -> list[tuple[Decimal, Decimal]]:
    code = _pair_code(pair)
    parser = _TableParser()
    parser.feed(html)

    candidates: list[tuple[Decimal, Decimal]] = []
    for row in parser.rows:
        code_index = next(
            (
                idx
                for idx, cell in enumerate(row)
                if cell.strip().upper() == code
                or cell.strip().upper().startswith(code + " ")
            ),
            None,
        )
        if code_index is None:
            continue

        numbers = [
            number
            for number in (_number(cell) for cell in row[code_index + 1 :])
            if number is not None
        ]
        if len(numbers) < 2:
            continue
        buy, sell = numbers[0], numbers[1]
        if sell <= buy:
            continue
        pair_value = (buy, sell)
        if pair_value not in candidates:
            candidates.append(pair_value)

    if not candidates:
        raise ValueError(f"Official bank page has no usable {code} buy/sell row")
    return candidates


def parse_isbank_midpoint(html: str, pair: str) -> Decimal:
    candidates = _candidate_quotes(html, pair)
    # Isbank's public page exposes one live bank buy/sell row per currency.
    buy, sell = candidates[0]
    return (buy + sell) / Decimal("2")


def parse_ziraat_midpoint(
    html: str,
    pair: str,
    *,
    primary_midpoint: Decimal,
    max_mapping_deviation_pct: Decimal = Decimal("5.00"),
) -> Decimal:
    candidates = _candidate_quotes(html, pair)
    primary = Decimal(str(primary_midpoint))
    if primary <= 0:
        raise ValueError("Primary Ziraat midpoint must be positive")

    midpoints = [
        (buy + sell) / Decimal("2")
        for buy, sell in candidates
    ]
    selected = min(midpoints, key=lambda value: abs(value - primary))
    deviation = abs(selected - primary) / primary * Decimal("100")
    if deviation > max_mapping_deviation_pct:
        raise ValueError(
            "No Ziraat official rate channel matches the displayed row: "
            f"closest deviation {deviation.quantize(Decimal('0.01'))}%"
        )
    return selected


def _fetch_html(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-BankSafetyVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(
            f"Official bank verifier returned HTTP {exc.code} for {url}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load official bank verifier {url}: {exc}") from exc


def fetch_isbank_midpoint(pair: str, timeout: int = 20) -> Decimal:
    return parse_isbank_midpoint(_fetch_html(ISBANK_URL, timeout), pair)


def fetch_ziraat_midpoint(
    pair: str,
    *,
    primary_midpoint: Decimal,
    timeout: int = 20,
) -> Decimal:
    return parse_ziraat_midpoint(
        _fetch_html(ZIRAAT_URL, timeout),
        pair,
        primary_midpoint=primary_midpoint,
    )
