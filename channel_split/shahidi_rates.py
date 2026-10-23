"""Read the customer quotes used by shahidi.site without reapplying margins."""
from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from urllib.request import Request, ProxyHandler, build_opener

DEFAULT_URL = "http://127.0.0.1:8003/api/rates/current"
RATE_KEYS = ("buy_lira", "sell_lira", "buy_usdt", "sell_usdt", "lira_to_usdt", "usdt_to_lira")


def parse_rates(payload: object) -> dict[str, Decimal]:
    raw = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("Shahidi response has no rates object")
    rates = {}
    for key in RATE_KEYS:
        try:
            value = Decimal(str(raw[key]))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Missing or nonnumeric Shahidi rate: {key}") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError(f"Invalid Shahidi rate: {key}")
        if key in RATE_KEYS[:4] and value != value.to_integral_value():
            raise ValueError(f"Shahidi toman rate must be a whole number: {key}")
        rates[key] = value
    for buy, sell in (("buy_lira", "sell_lira"), ("buy_usdt", "sell_usdt"), ("lira_to_usdt", "usdt_to_lira")):
        if rates[buy] < rates[sell]:
            raise ValueError(f"Crossed Shahidi rates: {buy}/{sell}")
    return rates


def fetch_shahidi_rates(url: str | None = None, timeout: float = 15) -> dict[str, Decimal]:
    endpoint = url or os.environ.get("KIANI_CUSTOMER_RATES_URL") or DEFAULT_URL
    request = Request(endpoint, headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "Kiani-ShahidiRates/1.0"})
    # This is a local service dependency; do not send it through global proxies.
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        payload = json.load(response)
    # No consumer cache, fallback, independent calculation, or extra margin.
    return parse_rates(payload)
