"""Fetch the same final customer rates published by shahidi.site."""
from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from urllib.request import ProxyHandler, Request, build_opener

DEFAULT_URL = "http://127.0.0.1:8003/api/rates/current"
CUSTOMER_RATE_KEYS = (
    "buy_lira",
    "sell_lira",
    "buy_usdt",
    "sell_usdt",
    "lira_to_usdt",
    "usdt_to_lira",
    "foreign_payment",
)


def parse_customer_rates(payload: object) -> dict[str, Decimal]:
    raw = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("Shahidi rates response is missing its rates object")
    rates: dict[str, Decimal] = {}
    for key in CUSTOMER_RATE_KEYS:
        try:
            value = Decimal(str(raw[key]))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Shahidi rates response is missing {key}") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError(f"Shahidi rate {key} must be finite and positive")
        if key in CUSTOMER_RATE_KEYS[:4] and value != value.to_integral_value():
            raise ValueError(f"Shahidi toman rate {key} must be a whole number")
        rates[key] = value

    for buy, sell in (
        ("buy_lira", "sell_lira"),
        ("buy_usdt", "sell_usdt"),
        ("lira_to_usdt", "usdt_to_lira"),
    ):
        if rates[buy] < rates[sell]:
            raise ValueError(f"Shahidi buy/sell rates are crossed: {buy}/{sell}")
    return rates


def fetch_shahidi_snapshot(timeout: float = 8) -> tuple[dict[str, Decimal], dict]:
    _feed_module = _kiani_akamai_module()
    if _feed_module.enabled():
        _feed_module.read_validated_feed()
    url = os.getenv("SHAHIDI_RATES_URL", DEFAULT_URL).strip()
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "Kiani-MiniApp-Rates/1.0",
        },
    )
    # The two services share a host; bypass any process-wide outbound proxy.
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        payload = json.load(response)
    rates = parse_customer_rates(payload)
    if _feed_module.enabled():
        _feed_module.validate_shahidi_market(payload["rates"])
    return rates, payload["rates"]


def fetch_customer_rates(timeout: float = 8) -> dict[str, Decimal]:
    return fetch_shahidi_snapshot(timeout=timeout)[0]


def miniapp_rate_payload(
    rates: dict[str, Decimal], raw_market: dict | None = None
) -> dict[str, int | float | str]:
    payload = {
        "buy_lira": int(rates["buy_lira"]),
        "sell_lira": int(rates["sell_lira"]),
        "buy_usdt": int(rates["buy_usdt"]),
        "sell_usdt": int(rates["sell_usdt"]),
        "lira_to_usdt": float(rates["lira_to_usdt"]),
        "usdt_to_lira": float(rates["usdt_to_lira"]),
        "foreign_payment": int(rates["foreign_payment"]),
        "TRY_BUY_TOMAN": int(rates["buy_lira"]),
        "TRY_SELL_TOMAN": int(rates["sell_lira"]),
        "RATE_SOURCE": "shahidi.site",
    }
    if isinstance(raw_market, dict):
        for key in ("USDT_IRR", "USDT_TRY"):
            if key in raw_market:
                try:
                    market_value = Decimal(str(raw_market[key]))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if market_value.is_finite() and market_value > 0:
                    payload[key] = float(market_value)
    if isinstance(raw_market, dict) and _kiani_akamai_module().enabled():
        for key in ("market_source", "market_source_count", "market_age_seconds", "market_feed_valid_until_utc",
                    "market_source_providers", "market_usdt_irr_age_seconds", "market_usdt_try_age_seconds",
                    "rate_mode", "transaction_rates_available", "minimum_sources",
                    "trading_minimum_sources", "display_minimum_sources", "source_agreement_max_deviation_pct"):
            if key in raw_market:
                payload[key] = raw_market[key]
    return payload


# Kiani Akamai cutover v2: shared runtime flag, no credentials or network I/O.
def _kiani_akamai_module():
    import sys
    from pathlib import Path
    folder = Path(__file__).resolve().parents[3] / "channel_split"
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    import akamai_rate_feed
    return akamai_rate_feed
