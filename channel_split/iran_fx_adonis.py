#!/usr/bin/env python3
"""Independent Adonis Exchange verifier for TRY/Toman."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ADONIS_URL = "https://adonis.exchange/en/p"
ADONIS_MAX_AGE = timedelta(minutes=90)
ADONIS_LOCAL_TZ = ZoneInfo("Europe/Istanbul")


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


def validate_adonis_page_freshness(
    raw_html: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = ADONIS_MAX_AGE,
) -> None:
    """Fail closed unless the rate table has a recent, dated page update.

    Adonis exposes one page-level 'Last update', not a TRY-specific timestamp.
    A fresh page update is necessary but cannot prove that TRY itself changed.
    """
    current = now or datetime.now(ADONIS_LOCAL_TZ)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Adonis freshness check requires timezone-aware now")
    local_now = current.astimezone(ADONIS_LOCAL_TZ)
    page_text = _text_from_html(raw_html)

    update_heading = re.search(r"\\bLast\\s+update\\b", page_text, re.IGNORECASE)
    if not update_heading:
        raise ValueError("Adonis page has no Last update field")

    date_match = re.search(
        r"\\b20\\d{2}-\\d{2}-\\d{2}\\b",
        page_text[: update_heading.start()],
    )
    if not date_match:
        raise ValueError("Adonis page has no dated rate-table header")
    try:
        page_date = datetime.strptime(date_match.group(0), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Adonis page has an invalid update date") from exc
    if page_date != local_now.date():
        raise ValueError(
            f"Adonis page date is not current: {page_date} != {local_now.date()}"
        )

    update_text = page_text[update_heading.end() : update_heading.end() + 100]
    match = re.match(
        r"\\s*(\\d+)\\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\\s+ago\\b",
        update_text,
        re.IGNORECASE,
    )
    if match:
        quantity = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith(("second", "sec")):
            age = timedelta(seconds=quantity)
        elif unit.startswith(("minute", "min")):
            age = timedelta(minutes=quantity)
        elif unit.startswith(("hour", "hr")):
            age = timedelta(hours=quantity)
        else:
            age = timedelta(days=quantity)
    elif re.match(r"\\s*just\\s+now\\b", update_text, re.IGNORECASE):
        age = timedelta(0)
    else:
        raise ValueError("Adonis page has an unrecognized Last update age")

    if age > max_age:
        raise ValueError(
            f"Adonis page is stale: age {age} exceeds {max_age}"
        )


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

    validate_adonis_page_freshness(raw_html)
    return parse_adonis_try_sell_toman(raw_html)
