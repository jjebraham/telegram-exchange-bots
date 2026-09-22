#!/usr/bin/env python3
"""Shared-admin pricing for Kiani channel transaction posts."""

from __future__ import annotations

import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PRICING_DB = Path("/home/kianirad2020/send_changes/pricing_settings.db")
BTCTURK_USDTTRY_URL = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"

DEFAULTS = {
    "user_tl_buy_adjustment_pct": Decimal("0.67"),
    "user_tl_sell_adjustment_pct": Decimal("-3.00"),
    "user_usdt_buy_adjustment_pct": Decimal("1.00"),
    "user_usdt_sell_adjustment_pct": Decimal("-1.00"),
    "user_try_to_usdt_adjustment_pct": Decimal("2.00"),
    "user_usdt_to_try_adjustment_pct": Decimal("-2.00"),
}


def _parse_pct(raw: object, key: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid pricing percentage {key}: {raw!r}") from exc
    if not value.is_finite() or value < Decimal("-50") or value > Decimal("50"):
        raise ValueError(f"Pricing percentage out of range for {key}: {value}")
    return value


def load_shared_adjustments(db_path: Path | None = None) -> dict[str, Decimal]:
    path = db_path or Path(
        os.environ.get("KIANI_PRICING_DB_PATH", str(DEFAULT_PRICING_DB))
    ).expanduser()
    if not path.is_file():
        raise RuntimeError(f"Kiani pricing database is missing: {path}")

    try:
        connection = sqlite3.connect(path, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout = 3000")
            rows = connection.execute(
                "SELECT key, value FROM pricing_settings "
                "WHERE key IN ({})".format(",".join("?" for _ in DEFAULTS)),
                tuple(DEFAULTS),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not read Kiani pricing database: {exc}") from exc

    found = {str(key): _parse_pct(value, str(key)) for key, value in rows}
    missing = [key for key in DEFAULTS if key not in found]
    if missing:
        raise RuntimeError(
            "Kiani pricing database is missing required settings: "
            + ", ".join(missing)
        )
    return found


def fetch_btcturk_usdt_try(
    url: str = BTCTURK_USDTTRY_URL,
    timeout: int = 15,
) -> Decimal:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Kiani-ChannelPricing/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"BTCTurk returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load BTCTurk USDT/TRY: {exc}") from exc

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("BTCTurk response has no ticker data")
    try:
        value = Decimal(str(items[0]["last"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("BTCTurk response has invalid last price") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("BTCTurk USDT/TRY price must be positive")
    return value


def _factor(adjustment_pct: Decimal) -> Decimal:
    return Decimal("1") + adjustment_pct / Decimal("100")


def _round_10(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1E1"), rounding=ROUND_HALF_UP)


def calculate_kiani_rates(
    market_usdt_toman: Decimal,
    market_usdt_try: Decimal,
    adjustments: dict[str, Decimal],
) -> dict[str, Decimal]:
    if market_usdt_toman <= 0 or market_usdt_try <= 0:
        raise ValueError("Market prices must be positive")

    required = set(DEFAULTS)
    missing = sorted(required - set(adjustments))
    if missing:
        raise ValueError("Missing Kiani adjustments: " + ", ".join(missing))

    base_try_toman = market_usdt_toman / market_usdt_try
    return {
        "buy_lira": _round_10(
            base_try_toman * _factor(adjustments["user_tl_buy_adjustment_pct"])
        ),
        "sell_lira": _round_10(
            base_try_toman * _factor(adjustments["user_tl_sell_adjustment_pct"])
        ),
        "buy_usdt": _round_10(
            market_usdt_toman
            * _factor(adjustments["user_usdt_buy_adjustment_pct"])
        ),
        "sell_usdt": _round_10(
            market_usdt_toman
            * _factor(adjustments["user_usdt_sell_adjustment_pct"])
        ),
        "lira_to_usdt": (
            market_usdt_try
            * _factor(adjustments["user_try_to_usdt_adjustment_pct"])
        ).quantize(Decimal("0.01")),
        "usdt_to_lira": (
            market_usdt_try
            * _factor(adjustments["user_usdt_to_try_adjustment_pct"])
        ).quantize(Decimal("0.01")),
    }
