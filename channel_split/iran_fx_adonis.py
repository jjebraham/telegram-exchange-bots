#!/usr/bin/env python3
"""Independent Adonis Exchange verifier for TRY/Toman."""

from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ADONIS_URL = "https://adonis.exchange/en/p"


def _text_from_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _positive_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Adonis TRY value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Adonis TRY value must be positive: {value!r}")
    return parsed


def parse_adonis_try_sell_toman(raw_html: str) -> Decimal:
    text = _text_from_html(raw_html)

    patterns = (
        r"TRY-IRR\s*Lira\s+to\s+Toman\s*([0-9][0-9,]*)\s*([0-9][0-9,]*)",
        r"TRY\s*Turkish\s+Lira\s*([0-9][0-9,]*)\s*([0-9][0-9,]*)",
        r"Lira\s+to\s+Toman\s*([0-9][0-9,]*)\s*([0-9][0-9,]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Adonis table order is Sell then Buy.
            return _positive_decimal(match.group(1))

    raise ValueError("Adonis page has no parseable TRY/Toman sell rate")


def fetch_adonis_try_sell_toman(
    url: str = ADONIS_URL,
    *,
    timeout: int = 20,
) -> Decimal:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "AlanChande-AdonisVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw_html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Adonis returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load Adonis: {exc}") from exc

    return parse_adonis_try_sell_toman(raw_html)
