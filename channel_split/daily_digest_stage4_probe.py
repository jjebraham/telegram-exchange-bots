#!/usr/bin/env python3
"""Read-only final-gap probe for the proposed AlanChande noon digest.

Stage 3 left two unresolved rows:
1) 100 IQD/Toman: the Dolarchand parser accidentally captured the literal
   quantity "100" from the heading instead of the quoted Toman rate.
2) The native TON token was renamed from TON to GRAM in June 2026, so current
   direct exchanges no longer expose TON/USDT under the old ticker.

This probe fixes the IQD parser and checks GRAM/USDT on direct exchange APIs.
It sends no Telegram messages, writes no databases, and changes no timers or
production configuration.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from iran_gold import parse_tgju_profile_current
from market_safety import SafetyObservation, evaluate_observation


TGJU_IQD_URL = "https://www.tgju.org/profile/price_iqd"
DOLARCHAND_IQD_URL = "https://dolarchand.com/en/currencies/IQD-to-IRR"

OKX_URL = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
GATE_URL = "https://api.gateio.ws/api/v4/spot/tickers"
KUCOIN_URL = "https://api.kucoin.com/api/v1/market/allTickers"
BITGET_URL = "https://api.bitget.com/api/v3/market/tickers?category=SPOT"

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.parts.append(clean)


def _visible(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(parser.parts)


def _number(value: Any) -> Decimal:
    text = str(value).translate(_DIGITS).replace(",", "").replace("٬", "").strip()
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text)
    if not match:
        raise ValueError(f"No numeric value in {value!r}")
    try:
        parsed = Decimal(match.group(0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value in {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Non-positive numeric value in {value!r}")
    return parsed


def _fetch_text(url: str, *, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "en-US,en;q=0.9,fa;q=0.7",
            "Accept-Encoding": "identity",
            "User-Agent": "AlanChande-DailyDigestStage4Probe/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(type(exc).__name__) from exc


def _fetch_json(url: str, *, timeout: int = 20) -> Any:
    return json.loads(_fetch_text(url, timeout=timeout))


def parse_dolarchand_iqd100_toman(html: str) -> Decimal:
    """Extract the explicit Toman quote for the 100-IQD market convention."""
    text = _visible(html).translate(_DIGITS)
    patterns = (
        r"Sell rate for\s+100\s+Iraqi Dinar\s+to\s+Toman\s+"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"نرخ فروش\s+100\s+دینار عراق\s+به تومان\s+"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    raise ValueError("Dolarchand has no explicit 100-IQD Toman sell rate")


def fetch_tgju_iqd100_toman() -> Decimal:
    # TGJU publishes IRR for one IQD. 100 IQD in toman = IRR * 100 / 10.
    return parse_tgju_profile_current(_fetch_text(TGJU_IQD_URL)) * Decimal("10")


def fetch_dolarchand_iqd100_toman() -> Decimal:
    return parse_dolarchand_iqd100_toman(_fetch_text(DOLARCHAND_IQD_URL))


def parse_okx_gram(payload: Any) -> Decimal:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected OKX ticker payload")
    for row in payload["data"]:
        if isinstance(row, dict) and row.get("instId") == "GRAM-USDT":
            return _number(row.get("last"))
    raise ValueError("OKX GRAM-USDT not found")


def fetch_okx_gram() -> Decimal:
    return parse_okx_gram(_fetch_json(OKX_URL))


def parse_gate_gram(payload: Any) -> Decimal:
    if not isinstance(payload, list):
        raise ValueError("Unexpected Gate ticker payload")
    for row in payload:
        if isinstance(row, dict) and row.get("currency_pair") == "GRAM_USDT":
            return _number(row.get("last"))
    raise ValueError("Gate GRAM_USDT not found")


def fetch_gate_gram() -> Decimal:
    return parse_gate_gram(_fetch_json(GATE_URL))


def parse_kucoin_gram(payload: Any) -> Decimal:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected KuCoin ticker payload")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("ticker"), list):
        raise ValueError("Unexpected KuCoin ticker data")
    for row in data["ticker"]:
        if isinstance(row, dict) and row.get("symbol") == "GRAM-USDT":
            return _number(row.get("last"))
    raise ValueError("KuCoin GRAM-USDT not found")


def fetch_kucoin_gram() -> Decimal:
    return parse_kucoin_gram(_fetch_json(KUCOIN_URL))


def parse_bitget_gram(payload: Any) -> Decimal:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected Bitget ticker payload")
    for row in payload["data"]:
        if isinstance(row, dict) and row.get("symbol") == "GRAMUSDT":
            return _number(row.get("lastPrice"))
    raise ValueError("Bitget GRAMUSDT not found")


def fetch_bitget_gram() -> Decimal:
    return parse_bitget_gram(_fetch_json(BITGET_URL))


def consensus(
    key: str,
    values: dict[str, Decimal],
    *,
    tolerance_pct: Decimal = Decimal("2.00"),
) -> tuple[str, Decimal | None, str, dict[str, Decimal]]:
    check = evaluate_observation(
        SafetyObservation(
            market_key=key,
            source_values=values,
            min_sources=2,
            max_source_deviation_pct=tolerance_pct,
        )
    )
    return check.decision, check.reference_value, check.reason, check.source_values


def _safe(label: str, fn: Any) -> Any | None:
    try:
        value = fn()
    except Exception as exc:
        print(f"SOURCE {label}: FAILED ({type(exc).__name__})")
        return None
    print(f"SOURCE {label}: FETCHED value={value}")
    return value


def _show(section: str, item: str, values: dict[str, Decimal]) -> None:
    decision, ref, reason, accepted = consensus(item, values)
    all_values = ", ".join(f"{k}={v}" for k, v in sorted(values.items())) or "none"
    print(
        f"{section:<7} {item:<10} {decision:<10} "
        f"reference={ref if ref is not None else '—'} "
        f"accepted={','.join(sorted(accepted)) or 'none'} all=[{all_values}]"
    )
    if decision != "VERIFIED":
        print(f"         reason: {reason}")


def run() -> None:
    print("READ-ONLY stage-4 probe: no sends, timers, database writes or config changes")

    print("\n===== 100 IQD / TOMAN =====")
    tgju = _safe("TGJU IQD", fetch_tgju_iqd100_toman)
    dolarchand = _safe("Dolarchand IQD", fetch_dolarchand_iqd100_toman)
    values: dict[str, Decimal] = {}
    if tgju is not None:
        values["tgju"] = tgju
    if dolarchand is not None:
        values["dolarchand"] = dolarchand
    _show("FX", "100 IQD", values)

    print("\n===== GRAM / USDT (formerly Toncoin / TON) =====")
    providers = {
        "okx": _safe("OKX GRAM", fetch_okx_gram),
        "gate": _safe("Gate GRAM", fetch_gate_gram),
        "kucoin": _safe("KuCoin GRAM", fetch_kucoin_gram),
        "bitget": _safe("Bitget GRAM", fetch_bitget_gram),
    }
    gram = {
        name: value
        for name, value in providers.items()
        if value is not None
    }
    _show("CRYPTO", "GRAM", gram)


if __name__ == "__main__":
    run()
