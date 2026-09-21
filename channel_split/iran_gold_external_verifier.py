#!/usr/bin/env python3
"""Independent Iran gold/coin verifier using Dolarchand public market data.

Dolarchand is treated as one external source family. Other sites that show
nearly identical values are not counted separately until upstream independence
is established.

Returned values are in Iranian toman, matching market_safety.iran_gold_observations.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DOLARCHAND_GOLD_URL = "https://dolarchand.com/en/gold-silver"

LABEL_PATTERNS = {
    "سکه امامی": r"Emami",
    "سکه بهار آزادی": r"Azadi",
    "نیم سکه": r"(?:½|1/2)\s*Azadi",
    "ربع سکه": r"(?:¼|1/4)\s*Azadi",
    "سکه گرمی": r"Gerami",
    "طلای ۱۸ عیار": r"Gold\s+18K",
    "مثقال طلا": r"Gold\s+Mesghal\s*\(Bazaar\)",
}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.parts.append(clean)


def _number(value: str) -> Decimal:
    token = value.replace(",", "").strip()
    try:
        parsed = Decimal(token)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Dolarchand numeric value: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Invalid Dolarchand numeric value: {value!r}")
    return parsed


def _visible_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return " ".join(parser.parts)


def parse_dolarchand_updated_at(text: str) -> datetime:
    match = re.search(
        r"Last\s+updated\s+"
        r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+"
        r"\d{1,2}:\d{2}\s+[AP]M)",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Dolarchand page has no parseable Last updated timestamp")

    try:
        naive = datetime.strptime(
            match.group(1),
            "%b %d, %Y, %I:%M %p",
        )
    except ValueError as exc:
        raise ValueError("Dolarchand Last updated timestamp is invalid") from exc

    # The public page timestamp matches the server-rendered ISO Z timestamp
    # observed in its payload, so interpret this public timestamp as UTC.
    return naive.replace(tzinfo=timezone.utc)


def _assert_fresh(
    updated_at: datetime,
    *,
    now: datetime | None = None,
    max_age_minutes: int = 240,
) -> None:
    current = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    age_seconds = (current - updated_at.astimezone(timezone.utc)).total_seconds()

    if age_seconds < -300:
        raise ValueError("Dolarchand timestamp is unexpectedly in the future")

    age_minutes = max(age_seconds, 0) / 60
    if age_minutes > max_age_minutes:
        raise ValueError(
            f"Dolarchand Iran-gold data is stale: {age_minutes:.1f} minutes old "
            f"(limit {max_age_minutes})"
        )


def parse_dolarchand_iran_gold(
    html: str,
    *,
    now: datetime | None = None,
    max_age_minutes: int = 240,
) -> dict[str, Decimal]:
    text = _visible_text(html)
    updated_at = parse_dolarchand_updated_at(text)
    _assert_fresh(
        updated_at,
        now=now,
        max_age_minutes=max_age_minutes,
    )

    values: dict[str, Decimal] = {}
    for label, label_pattern in LABEL_PATTERNS.items():
        pattern = re.compile(
            rf"(?:{label_pattern})\s+"
            rf"(?:[-+]?\d+(?:\.\d+)?%\s+)?"
            rf"Buy\s+([0-9][0-9,]*)\s+"
            rf"Sell\s+([0-9][0-9,]*)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            raise ValueError(f"Dolarchand page is missing {label}")

        buy = _number(match.group(1))
        sell = _number(match.group(2))
        if sell <= 0 or buy <= 0:
            raise ValueError(f"Dolarchand {label} has non-positive quote")

        # TGJU exposes a single market price. Midpoint is the neutral comparison
        # value when Dolarchand exposes separate buy/sell sides.
        values[label] = (buy + sell) / Decimal("2")

    return values


def _fetch_html(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,fa;q=0.7",
            "Accept-Encoding": "identity",
            "User-Agent": "AlanChande-IranGoldSafetyVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(
            f"Dolarchand Iran-gold verifier returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not load Dolarchand Iran-gold verifier: {exc}"
        ) from exc


def fetch_dolarchand_iran_gold(
    *,
    timeout: int = 20,
    max_age_minutes: int = 240,
) -> dict[str, Decimal]:
    return parse_dolarchand_iran_gold(
        _fetch_html(DOLARCHAND_GOLD_URL, timeout),
        max_age_minutes=max_age_minutes,
    )
