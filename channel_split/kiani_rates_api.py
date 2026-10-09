"""Fetch the shared Kiani customer rate snapshot for publisher jobs."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"
RATE_KEYS = (
    "buy_lira",
    "sell_lira",
    "buy_usdt",
    "sell_usdt",
    "lira_to_usdt",
    "usdt_to_lira",
)


def _positive_decimal(value: Any, key: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Rate {key!r} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Rate {key!r} must be positive")
    return parsed


def fetch_kiani_rates(
    url: str | None = None,
    timeout: int = 20,
    retries: int = 3,
) -> dict[str, Decimal]:
    """Fetch all six Kiani customer rates from one API response."""

    endpoint = (
        url
        or os.environ.get("KIANI_RATES_URL", "").strip()
        or DEFAULT_RATES_URL
    )
    last_error: Exception | None = None

    for attempt in range(1, max(1, retries) + 1):
        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "Kiani-TelegramPublisher/2.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            last_error = RuntimeError(
                f"Kiani rates API returned HTTP {exc.code}: {detail}"
            )
            if exc.code in {502, 503, 504} and attempt < max(1, retries):
                time.sleep(attempt)
                continue
            raise last_error from exc
        except (URLError, TimeoutError) as exc:
            last_error = RuntimeError(f"Could not load Kiani rates: {exc}")
            if attempt < max(1, retries):
                time.sleep(attempt)
                continue
            raise last_error from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not decode Kiani rates response: {exc}") from exc

        raw = payload.get("rates") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise ValueError("Kiani rates API response has no rates object")

        missing = [key for key in RATE_KEYS if key not in raw]
        if missing:
            raise ValueError("Missing Kiani rates: " + ", ".join(missing))
        return {key: _positive_decimal(raw[key], key) for key in RATE_KEYS}

    raise RuntimeError(f"Could not load Kiani rates: {last_error}")
