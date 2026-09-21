#!/usr/bin/env python3
"""Independent Turkey FX/gold verifier using Altinkaynak public services."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

CURRENCY_URL = "https://static.altinkaynak.com/public/Currency"
GOLD_URL = "https://static.altinkaynak.com/public/Gold"

# Altinkaynak public-service codes. PGA/PC/PY/PT represent physical retail
# gram, quarter, half and full ("Teklik") products and are the closest match to
# the Kapalicarsi products on the AlanChande board.
GOLD_CODES = {
    "gram": "PGA",
    "quarter": "PC",
    "half": "PY",
    "tam": "PT",
}


def _tr_decimal(value: str) -> Decimal:
    cleaned = str(value).strip().replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Altinkaynak decimal: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Invalid positive Altinkaynak value: {value!r}")
    return parsed


def _parse_updated(value: str) -> datetime:
    try:
        naive = datetime.strptime(str(value).strip(), "%d.%m.%Y %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"Invalid Altinkaynak update time: {value!r}") from exc
    return naive.replace(tzinfo=ISTANBUL_TZ)


def _assert_fresh(
    updated: datetime,
    *,
    now: datetime | None = None,
    max_age_minutes: int = 90,
) -> None:
    current = now.astimezone(ISTANBUL_TZ) if now else datetime.now(ISTANBUL_TZ)
    age_seconds = (current - updated.astimezone(ISTANBUL_TZ)).total_seconds()
    if age_seconds < -300:
        raise ValueError("Altinkaynak timestamp is unexpectedly in the future")
    age_minutes = max(age_seconds, 0) / 60
    if age_minutes > max_age_minutes:
        raise ValueError(
            f"Altinkaynak data is stale: {age_minutes:.1f} minutes old "
            f"(limit {max_age_minutes})"
        )


def _mid(row: dict[str, object]) -> Decimal:
    buy = _tr_decimal(str(row["Alis"]))
    sell = _tr_decimal(str(row["Satis"]))
    if sell < buy:
        raise ValueError(
            f"Altinkaynak crossed quote for {row.get('Kod')}: "
            f"buy={buy} sell={sell}"
        )
    return (buy + sell) / Decimal("2")


def _fetch_json(url: str, timeout: int = 15) -> list[dict[str, object]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-SafetyVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Altinkaynak returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load Altinkaynak: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError("Altinkaynak response is not a JSON list")
    rows = [row for row in payload if isinstance(row, dict)]
    if not rows:
        raise ValueError("Altinkaynak response contains no rows")
    return rows


def parse_currency_rows(
    rows: list[dict[str, object]],
    *,
    now: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Decimal]:
    by_code = {str(row.get("Kod", "")).strip(): row for row in rows}
    result: dict[str, Decimal] = {}
    for code, pair in (("USD", "USD/TRY"), ("EUR", "EUR/TRY")):
        row = by_code.get(code)
        if row is None:
            raise ValueError(f"Altinkaynak currency source is missing {code}")
        updated = _parse_updated(str(row.get("GuncellenmeZamani", "")))
        _assert_fresh(
            updated,
            now=now,
            max_age_minutes=max_age_minutes,
        )
        result[pair] = _mid(row)
    return result


def parse_gold_rows(
    rows: list[dict[str, object]],
    *,
    now: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Decimal]:
    by_code = {str(row.get("Kod", "")).strip(): row for row in rows}
    result: dict[str, Decimal] = {}
    for asset_key, code in GOLD_CODES.items():
        row = by_code.get(code)
        if row is None:
            raise ValueError(
                f"Altinkaynak gold source is missing {asset_key} ({code})"
            )
        updated = _parse_updated(str(row.get("GuncellenmeZamani", "")))
        _assert_fresh(
            updated,
            now=now,
            max_age_minutes=max_age_minutes,
        )
        result[asset_key] = _mid(row)
    return result


def fetch_altinkaynak_currency(
    *,
    timeout: int = 15,
    now: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Decimal]:
    return parse_currency_rows(
        _fetch_json(CURRENCY_URL, timeout),
        now=now,
        max_age_minutes=max_age_minutes,
    )


def fetch_altinkaynak_gold(
    *,
    timeout: int = 15,
    now: datetime | None = None,
    max_age_minutes: int = 90,
) -> dict[str, Decimal]:
    return parse_gold_rows(
        _fetch_json(GOLD_URL, timeout),
        now=now,
        max_age_minutes=max_age_minutes,
    )
