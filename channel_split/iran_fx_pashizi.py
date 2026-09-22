#!/usr/bin/env python3
"""Independent Pashizi verifier for Iran free-market FX."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _parse_update_text(text: str) -> str | None:
    match = re.search(
        r"last\s+update\s*:\s*"
        r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
        r"(?:,?\s+[A-Za-z]+\s+[0-9]{1,2})?"
        r"\s+([0-2][0-9]):([0-5][0-9])",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return f"{match.group(1).title()} {match.group(2)}:{match.group(3)}"


def parse_pashizi_fx_page(raw_html: str) -> tuple[dict[str, Decimal], str | None]:
    """Parse Pashizi's all-rates page when the table is server-rendered."""
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

    return rates, _parse_update_text(text)


def parse_pashizi_currency_detail(
    raw_html: str,
    code: str,
) -> tuple[Decimal, str | None]:
    """Parse one Pashizi currency detail page.

    The detail page labels its headline price as the current IRR free-market
    rate and its converter says it is based on the sell rate. Using that sell
    rate as the independent verifier is intentionally conservative; TGJU
    remains the display source.
    """
    normalized_code = code.upper()
    if normalized_code not in TARGET_CODES:
        raise ValueError(f"Unsupported Pashizi currency: {code}")

    title_match = re.search(
        r"(?is)<title[^>]*>(.*?)</title>",
        raw_html,
    )
    title = (
        " ".join(html.unescape(title_match.group(1)).split())
        if title_match
        else ""
    )
    visible = _text_from_html(raw_html)
    search_text = f"{title} {visible}".strip()

    exact = re.search(
        rf"(?<![A-Z0-9]){re.escape(normalized_code)}(?![A-Z0-9])"
        rf"\s+Price\s+Today\s*:\s*"
        rf"([0-9][0-9,]*)\s*IRR",
        search_text,
        re.IGNORECASE,
    )
    if exact is None:
        exact = re.search(
            rf"(?<![A-Z0-9]){re.escape(normalized_code)}(?![A-Z0-9])"
            rf".{{0,120}}?([0-9][0-9,]*)\s*IRR",
            search_text,
            re.IGNORECASE,
        )
    if exact is None:
        raise ValueError(
            f"Pashizi detail page has no current {normalized_code}/IRR rate"
        )

    rate_toman = _positive_decimal(exact.group(1)) / Decimal("10")
    return rate_toman, _parse_update_text(visible)


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


def _fetch_html(url: str, timeout: int) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "AlanChande-PashiziVerifier/1.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Pashizi returned HTTP {exc.code} for {url}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load Pashizi {url}: {exc}") from exc


def _ensure_fresh(
    update_texts: list[str],
    *,
    max_age_minutes: int,
) -> None:
    if not update_texts:
        raise ValueError("Pashizi has no parseable last-update time")

    oldest_age = max(_age_minutes(value) for value in update_texts)
    if oldest_age > max(max_age_minutes, 1):
        raise ValueError(
            f"Pashizi data is stale: oldest rate is {oldest_age:.0f} minutes old "
            f"(limit {max_age_minutes})"
        )


def _fetch_detail_rates(
    base_url: str,
    *,
    timeout: int,
    max_workers: int = 6,
) -> tuple[dict[str, Decimal], list[str]]:
    rates: dict[str, Decimal] = {}
    updates: list[str] = []
    errors: dict[str, str] = {}

    def fetch_one(code: str) -> tuple[str, Decimal, str | None]:
        raw = _fetch_html(
            f"{base_url.rstrip('/')}/currency/{code.lower()}",
            timeout,
        )
        rate, updated = parse_pashizi_currency_detail(raw, code)
        return code, rate, updated

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as pool:
        futures = {
            pool.submit(fetch_one, code): code
            for code in TARGET_CODES
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                parsed_code, rate, updated = future.result()
            except Exception as exc:
                errors[code] = f"{type(exc).__name__}: {exc}"
                continue
            rates[parsed_code] = rate
            if updated:
                updates.append(updated)

    missing = [code for code in TARGET_CODES if code not in rates]
    if missing:
        details = "; ".join(
            f"{code}={errors.get(code, 'missing')}"
            for code in missing[:5]
        )
        raise ValueError(
            "Pashizi detail fallback is missing required currencies: "
            + ", ".join(missing)
            + (f" | {details}" if details else "")
        )

    return rates, updates


def fetch_pashizi_iran_fx(
    url: str = PASHIZI_URL,
    *,
    timeout: int = 25,
    max_age_minutes: int = 900,
) -> dict[str, Decimal]:
    raw_html = _fetch_html(url, timeout)
    landing_update = _parse_update_text(_text_from_html(raw_html))

    try:
        rates, parsed_update = parse_pashizi_fx_page(raw_html)
        updates = [
            value
            for value in (parsed_update, landing_update)
            if value is not None
        ]
        _ensure_fresh(updates, max_age_minutes=max_age_minutes)
        return rates
    except ValueError as landing_error:
        # The public site sometimes sends a client-rendered shell to urllib
        # even though browsers/search crawlers see the full table. Detail
        # pages are separately addressable and expose the current sell rate.
        rates, detail_updates = _fetch_detail_rates(
            url,
            timeout=timeout,
        )
        updates = (
            [landing_update] if landing_update is not None else detail_updates
        )
        try:
            _ensure_fresh(updates, max_age_minutes=max_age_minutes)
        except ValueError as freshness_error:
            raise ValueError(
                f"Pashizi landing parse failed ({landing_error}); "
                f"detail fallback freshness failed ({freshness_error})"
            ) from freshness_error
        return rates
