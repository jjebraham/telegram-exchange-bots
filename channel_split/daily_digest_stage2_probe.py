#!/usr/bin/env python3
"""Read-only stage-2 source probe for the proposed AlanChande noon digest.

No Telegram sends, timer changes, database writes, or production configuration
changes occur here. The probe tests candidate second/third source families for:
- Iran FX: Dolarchand alongside the existing TGJU/Pashizi collectors
- 100 IQD: TGJU Iran-market quote + Tehran Exchange desk quote
- XAU/USD: TGJU global ounce + keyless Gold API spot quote
- Crypto/USD: two direct exchange-operated public market APIs (Binance + OKX)

A successful probe is still not production approval. Production integration must
add freshness checks, fail-closed safety observations, accepted-history updates,
and formatter tests before any timer is enabled.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from iran_fx import fetch_iran_open_market_fx
from market_safety import SafetyObservation, evaluate_observation


DOLARCHAND_BASE = "https://dolarchand.com/en/currencies"
TGJU_IQD_URL = "https://www.tgju.org/profile/price_iqd"
TXE_URL = "https://www.txe.ir/singleCourencies"
TGJU_XAU_URL = "https://www.tgju.org/profile/ons"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
BINANCE_TICKERS_URL = "https://api.binance.com/api/v3/ticker/24hr"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"

FX_CODES = ("USD", "EUR", "AED", "TRY", "CNY", "CAD", "AUD", "GBP", "AFN")
CRYPTO_SYMBOLS = ("BTC", "ETH", "BNB", "SHIB", "ADA", "DOGE", "TON", "NOT", "SOL", "XRP")

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


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"td", "th"}:
            self.in_cell = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(" ".join("".join(self.parts).split()))
            self.in_cell = False
            self.parts = []
        elif tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row = []


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


def _visible(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(parser.parts)


def _fetch_text(url: str, *, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "en-US,en;q=0.9,fa;q=0.7",
            "Accept-Encoding": "identity",
            "User-Agent": "AlanChande-DailyDigestSourceProbe/1.0",
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


def parse_dolarchand_sell_toman(html: str) -> Decimal:
    text = _visible(html).translate(_DIGITS)
    patterns = (
        r"Sell rate for .*? to Toman\s+([0-9]{1,3}(?:,[0-9]{3})+)",
        r"about\s+([0-9]{1,3}(?:,[0-9]{3})+)\s+Toman",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    raise ValueError("Dolarchand page has no parseable Toman sell/current rate")


def fetch_dolarchand_fx(code: str) -> Decimal:
    code = code.upper()
    if code not in FX_CODES:
        raise ValueError(f"Unsupported Dolarchand FX code: {code}")
    return parse_dolarchand_sell_toman(
        _fetch_text(f"{DOLARCHAND_BASE}/{code}-to-IRR")
    )


def parse_tgju_profile_current(html: str) -> Decimal:
    text = _visible(html).translate(_DIGITS)
    match = re.search(
        r"(?:نرخ\s*فعلی|Last)\s*:*
\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        # Keep a one-line fallback because some mirrors omit the colon.
        match = re.search(
            r"(?:نرخ\s*فعلی|Last).*?([0-9][0-9,]*(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
    if not match:
        raise ValueError("TGJU profile has no parseable current value")
    return _number(match.group(1))


def fetch_tgju_iqd100_toman() -> Decimal:
    # TGJU profile price_iqd is IRR per 1 IQD. Convert 100 IQD to toman:
    # value_rial * 100 / 10 == value_rial * 10.
    return parse_tgju_profile_current(_fetch_text(TGJU_IQD_URL)) * Decimal("10")


def parse_txe_iqd100_toman(html: str) -> Decimal:
    parser = _TableRows()
    parser.feed(html)
    for row in parser.rows:
        if not row:
            continue
        label = row[0].replace("ي", "ی").replace("ك", "ک")
        if "دینار عراق" not in label:
            continue
        numeric: list[Decimal] = []
        for cell in row[1:]:
            try:
                numeric.append(_number(cell))
            except ValueError:
                continue
        if len(numeric) < 2:
            raise ValueError("Tehran Exchange IQD row lacks buy/sell")
        midpoint_per_iqd = (numeric[0] + numeric[1]) / Decimal("2")
        return midpoint_per_iqd * Decimal("100")
    raise ValueError("Tehran Exchange table has no Iraqi dinar row")


def fetch_txe_iqd100_toman() -> Decimal:
    return parse_txe_iqd100_toman(_fetch_text(TXE_URL))


def fetch_tgju_xau_usd() -> Decimal:
    return parse_tgju_profile_current(_fetch_text(TGJU_XAU_URL))


@dataclass(frozen=True)
class GoldApiQuote:
    price: Decimal
    updated_at: datetime | None


def parse_gold_api(payload: Any) -> GoldApiQuote:
    if not isinstance(payload, dict):
        raise ValueError("Gold API response is not an object")
    price = _number(payload.get("price"))
    raw_time = payload.get("updatedAt")
    updated: datetime | None = None
    if isinstance(raw_time, str) and raw_time.strip():
        try:
            updated = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            updated = None
    return GoldApiQuote(price=price, updated_at=updated)


def fetch_gold_api_xau() -> GoldApiQuote:
    return parse_gold_api(_fetch_json(GOLD_API_URL))


def parse_binance_prices(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, list):
        raise ValueError("Binance ticker response is not a list")
    wanted = {f"{symbol}USDT": symbol for symbol in CRYPTO_SYMBOLS}
    result: dict[str, Decimal] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        pair = str(row.get("symbol", ""))
        symbol = wanted.get(pair)
        if symbol:
            result[symbol] = _number(row.get("lastPrice"))
    return result


def fetch_binance_prices() -> dict[str, Decimal]:
    return parse_binance_prices(_fetch_json(BINANCE_TICKERS_URL))


def parse_okx_prices(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("OKX ticker response has unexpected structure")
    wanted = {f"{symbol}-USDT": symbol for symbol in CRYPTO_SYMBOLS}
    result: dict[str, Decimal] = {}
    for row in payload["data"]:
        if not isinstance(row, dict):
            continue
        symbol = wanted.get(str(row.get("instId", "")))
        if symbol:
            result[symbol] = _number(row.get("last"))
    return result


def fetch_okx_prices() -> dict[str, Decimal]:
    return parse_okx_prices(_fetch_json(OKX_TICKERS_URL))


def consensus(
    key: str,
    values: dict[str, Decimal],
    *,
    tolerance_pct: Decimal = Decimal("2.00"),
) -> tuple[str, Decimal | None, str]:
    check = evaluate_observation(
        SafetyObservation(
            market_key=key,
            source_values=values,
            min_sources=2,
            max_source_deviation_pct=tolerance_pct,
        )
    )
    return check.decision, check.reference_value, check.reason


def _safe(label: str, fn: Any) -> Any | None:
    try:
        value = fn()
    except Exception as exc:
        print(f"SOURCE {label}: FAILED ({type(exc).__name__})")
        return None
    print(f"SOURCE {label}: FETCHED")
    return value


def _print_consensus(section: str, item: str, values: dict[str, Decimal]) -> None:
    decision, ref, reason = consensus(item, values)
    rendered = ", ".join(f"{k}={v}" for k, v in sorted(values.items())) or "none"
    print(
        f"{section:<7} {item:<12} {decision:<10} "
        f"reference={ref if ref is not None else '—'} sources=[{rendered}]"
    )
    if decision != "VERIFIED":
        print(f"         reason: {reason}")


def run() -> None:
    print("READ-ONLY stage-2 source probe: no sends, timers, or database writes")

    tgju_fx = _safe("TGJU FX", fetch_iran_open_market_fx) or {}
    print("\n===== IRAN FX: TGJU + DOLARCHAND =====")
    for code in FX_CODES:
        dolarchand = _safe(f"Dolarchand {code}", lambda code=code: fetch_dolarchand_fx(code))
        values: dict[str, Decimal] = {}
        if code in tgju_fx:
            values["tgju"] = tgju_fx[code]
        if dolarchand is not None:
            values["dolarchand"] = dolarchand
        _print_consensus("FX", code, values)

    print("\n===== 100 IQD/TOMAN =====")
    tgju_iqd = _safe("TGJU IQD", fetch_tgju_iqd100_toman)
    txe_iqd = _safe("Tehran Exchange IQD", fetch_txe_iqd100_toman)
    iqd_values = {}
    if tgju_iqd is not None:
        iqd_values["tgju"] = tgju_iqd
    if txe_iqd is not None:
        iqd_values["txe"] = txe_iqd
    _print_consensus("FX", "100 IQD", iqd_values)

    print("\n===== XAU/USD =====")
    tgju_xau = _safe("TGJU ounce", fetch_tgju_xau_usd)
    gold_api = _safe("Gold API", fetch_gold_api_xau)
    xau_values = {}
    if tgju_xau is not None:
        xau_values["tgju"] = tgju_xau
    if gold_api is not None:
        xau_values["gold-api"] = gold_api.price
        if gold_api.updated_at is not None:
            age = (
                datetime.now(timezone.utc)
                - gold_api.updated_at.astimezone(timezone.utc)
            ).total_seconds() / 60
            print(f"Gold API age: {age:.1f} minutes")
    _print_consensus("GOLD", "XAU/USD", xau_values)

    print("\n===== CRYPTO/USD: BINANCE + OKX =====")
    binance = _safe("Binance spot", fetch_binance_prices) or {}
    okx = _safe("OKX spot", fetch_okx_prices) or {}
    for symbol in CRYPTO_SYMBOLS:
        values = {}
        if symbol in binance:
            values["binance"] = binance[symbol]
        if symbol in okx:
            values["okx"] = okx[symbol]
        _print_consensus("CRYPTO", symbol, values)


if __name__ == "__main__":
    run()
