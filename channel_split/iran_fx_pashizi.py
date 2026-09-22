#!/usr/bin/env python3
"""Independent Pashizi verifier for Iran free-market FX."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PASHIZI_URL = "https://www.pashizi.com/en"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

TARGET_CODES = (
    "USD", "EUR", "GBP", "CHF", "CAD", "AUD", "SEK", "NOK", "RUB",
    "THB", "SGD", "HKD", "AZN", "DKK", "AED", "TRY", "CNY", "SAR",
    "INR", "MYR", "AFN", "KWD", "BHD", "OMR", "QAR",
)

_WEEKDAYS = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}


def _text_from_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _positive_decimal(value: str) -> Decimal:
    try:
        number = Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Pashizi value: {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"Pashizi value must be positive: {value!r}")
    return number


def parse_pashizi_fx_page(raw_html: str) -> tuple[dict[str, Decimal], str | None]:
    text = _text_from_html(raw_html)
    rates: dict[str, Decimal] = {}

    for code in TARGET_CODES:
        pattern = re.compile(
            rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])"
            rf".{{0,160}}?Sell\s*\(IRR\)\s*([0-9][0-9,]*)"
            rf".{{0,100}}?Buy\s*\(IRR\)\s*([0-9][0-9,]*)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            continue
        sell_rial = _positive_decimal(match.group(1))
        buy_rial = _positive_decimal(match.group(2))
        rates[code] = ((sell_rial + buy_rial) / Decimal("2")) / Decimal("10")

    missing = [code for code in TARGET_CODES if code not in rates]
    if missing:
        raise ValueError(
            "Pashizi is missing required currencies: " + ", ".join(missing)
        )

    update_match = re.search(
        r"last\s+update\s*:\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([0-2][0-9]):([0-5][0-9])",
        text,
        re.IGNORECASE,
    )
    update_text = (
        f"{update_match.group(1).title()} {update_match.group(2)}:{update_match.group(3)}"
        if update_match
        else None
    )
    return rates, update_text


def _age_minutes(update_text: str, now: datetime | None = None) -> float:
    match = re.fullmatch(
        r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([0-2][0-9]):([0-5][0-9])",
        update_text,
    )
    if not match:
        raise ValueError(f"Invalid Pashizi update time: {update_text!r}")

    current = (now or datetime.now(TEHRAN_TZ)).astimezone(TEHRAN_TZ)
    target_weekday = _WEEKDAYS[match.group(1)]
    days_back = (current.weekday() - target_weekday) % 7
    candidate = current.replace(
        hour=int(match.group(2)),
        minute=int(match.group(3)),
        second=0,
        microsecond=0,
    ) - timedelta(days=days_back)
    if candidate > current:
        candidate -= timedelta(days=7)
    return (current - candidate).total_seconds() / 60


def fetch_pashizi_iran_fx(
    url: str = PASHIZI_URL,
    *,
    timeout: int = 25,
    max_age_minutes: int = 900,
) -> dict[str, Decimal]:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "AlanChande-PashiziVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw_html = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Pashizi returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load Pashizi: {exc}") from exc

    rates, update_text = parse_pashizi_fx_page(raw_html)
    if update_text is None:
        raise ValueError("Pashizi page has no parseable last-update time")

    age = _age_minutes(update_text)
    if age > max(max_age_minutes, 1):
        raise ValueError(
            f"Pashizi data is stale: {age:.0f} minutes old "
            f"(limit {max_age_minutes})"
        )
    return rates
