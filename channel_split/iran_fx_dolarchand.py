#!/usr/bin/env python3
"""Optional Dolarchand verifier for Iran free-market FX.

This module is intentionally independent of the public formatter. It fetches
one Dolarchand detail page per requested currency and returns partial results so
one unavailable currency does not discard the rest of the verifier.
"""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DOLARCHAND_FX_BASE = "https://dolarchand.com/en/currencies"


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(html.unescape(data).split())
        if clean:
            self.parts.append(clean)


def _visible(raw_html: str) -> str:
    parser = _VisibleText()
    parser.feed(raw_html)
    return " ".join(parser.parts)


def _positive_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Dolarchand value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Dolarchand value must be positive: {value!r}")
    return parsed


def parse_dolarchand_toman_rate(raw_html: str) -> Decimal:
    text = _visible(raw_html)
    patterns = (
        r"Sell rate for .*? to Toman\s+([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"about\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+Toman",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _positive_decimal(match.group(1))
    raise ValueError("Dolarchand page has no parseable Toman rate")


def _fetch_one(code: str, timeout: int) -> Decimal:
    normalized = code.upper().strip()
    if not re.fullmatch(r"[A-Z]{3}", normalized):
        raise ValueError(f"Invalid currency code: {code!r}")
    url = f"{DOLARCHAND_FX_BASE}/{normalized}-to-IRR"
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,fa;q=0.7",
            "Accept-Encoding": "identity",
            "User-Agent": "AlanChande-IranFXVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw_html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(type(exc).__name__) from exc
    return parse_dolarchand_toman_rate(raw_html)


def fetch_dolarchand_iran_fx(
    codes: Iterable[str],
    *,
    timeout: int = 20,
    max_workers: int = 8,
) -> tuple[dict[str, Decimal], dict[str, str]]:
    """Fetch requested FX rates concurrently.

    Returns (rates, errors). Partial success is intentional: each available
    Dolarchand quote can act as a third source without making Dolarchand itself
    a single point of failure for the entire Iran-FX post.
    """
    normalized_codes = tuple(dict.fromkeys(code.upper().strip() for code in codes))
    rates: dict[str, Decimal] = {}
    errors: dict[str, str] = {}

    workers = max(1, min(max_workers, len(normalized_codes) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_one, code, timeout): code
            for code in normalized_codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                rates[code] = future.result()
            except Exception as exc:
                errors[code] = f"{type(exc).__name__}: {exc}"[:200]

    return rates, errors
