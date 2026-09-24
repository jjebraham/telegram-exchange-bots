#!/usr/bin/env python3
"""Read-only stage-3 probe for unresolved AlanChande daily-digest sources.

This probe sends no Telegram messages, writes no databases, and changes no
timers/configuration. It focuses only on rows that were still blocked after the
stage-2 probe:
- 100 IQD/Toman: TGJU + Dolarchand
- XAU/USD: TGJU + Gold API, with Dolarchand as an additional observed provider
- Crypto/USD: OKX + Gate + KuCoin + Bybit direct exchange-operated spot feeds

The production digest remains disabled until these candidates are promoted into
normal collectors with freshness validation, fail-closed safety checks and
accepted-history handling.
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
TGJU_XAU_URL = "https://www.tgju.org/profile/ons"
DOLARCHAND_XAU_URL = "https://dolarchand.com/en/gold-silver/GOLD-OUNCE-to-IRR"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"

OKX_URL = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
GATE_URL = "https://api.gateio.ws/api/v4/spot/tickers"
KUCOIN_URL = "https://api.kucoin.com/api/v1/market/allTickers"
BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=spot"

CRYPTO_SYMBOLS = (
    "BTC", "ETH", "BNB", "SHIB", "ADA",
    "DOGE", "TON", "NOT", "SOL", "XRP",
)

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
            "User-Agent": "AlanChande-DailyDigestStage3Probe/1.0",
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


def parse_dolarchand_rate(html: str, *, label_hint: str) -> Decimal:
    """Parse the displayed sell/current rate from a Dolarchand detail page."""
    text = _visible(html).translate(_DIGITS)
    patterns = (
        rf"Sell rate for {re.escape(label_hint)} .*?\s+([0-9][0-9,.]*)",
        r"Sell rate .*?\s+([0-9][0-9,.]*)",
        r"about\s+([0-9][0-9,.]*)\s+(?:Toman|USD)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    raise ValueError("Dolarchand detail page has no parseable sell/current rate")


def fetch_tgju_iqd100_toman() -> Decimal:
    # TGJU publishes IRR per one IQD. 100 IQD in toman = IRR * 100 / 10.
    raw_rial = parse_tgju_profile_current(_fetch_text(TGJU_IQD_URL))
    return raw_rial * Decimal("10")


def fetch_dolarchand_iqd100_toman() -> Decimal:
    # This dedicated page explicitly quotes 100 Iraqi dinars in toman.
    return parse_dolarchand_rate(
        _fetch_text(DOLARCHAND_IQD_URL),
        label_hint="Iraqi Dinar",
    )


def fetch_tgju_xau_usd() -> Decimal:
    return parse_tgju_profile_current(_fetch_text(TGJU_XAU_URL))


def fetch_dolarchand_xau_usd() -> Decimal:
    return parse_dolarchand_rate(
        _fetch_text(DOLARCHAND_XAU_URL),
        label_hint="Gold Ounce (Global)",
    )


def fetch_gold_api_xau_usd() -> Decimal:
    payload = _fetch_json(GOLD_API_URL)
    if not isinstance(payload, dict):
        raise ValueError("Gold API response is not an object")
    return _number(payload.get("price"))


def _select_pairs(rows: list[dict[str, Any]], pair_key: str, price_key: str, *, separator: str) -> dict[str, Decimal]:
    wanted = {f"{symbol}{separator}USDT": symbol for symbol in CRYPTO_SYMBOLS}
    result: dict[str, Decimal] = {}
    for row in rows:
        pair = str(row.get(pair_key, ""))
        symbol = wanted.get(pair)
        if not symbol:
            continue
        try:
            result[symbol] = _number(row.get(price_key))
        except ValueError:
            continue
    return result


def parse_okx(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected OKX ticker payload")
    return _select_pairs(payload["data"], "instId", "last", separator="-")


def fetch_okx() -> dict[str, Decimal]:
    return parse_okx(_fetch_json(OKX_URL))


def parse_gate(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, list):
        raise ValueError("Unexpected Gate ticker payload")
    # Gate uses BTC_USDT.
    wanted = {f"{symbol}_USDT": symbol for symbol in CRYPTO_SYMBOLS}
    result: dict[str, Decimal] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = wanted.get(str(row.get("currency_pair", "")))
        if symbol:
            try:
                result[symbol] = _number(row.get("last"))
            except ValueError:
                pass
    return result


def fetch_gate() -> dict[str, Decimal]:
    return parse_gate(_fetch_json(GATE_URL))


def parse_kucoin(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected KuCoin ticker payload")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("ticker"), list):
        raise ValueError("Unexpected KuCoin ticker data")
    return _select_pairs(data["ticker"], "symbol", "last", separator="-")


def fetch_kucoin() -> dict[str, Decimal]:
    return parse_kucoin(_fetch_json(KUCOIN_URL))


def parse_bybit(payload: Any) -> dict[str, Decimal]:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Bybit ticker payload")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("list"), list):
        raise ValueError("Unexpected Bybit ticker data")
    return _select_pairs(result["list"], "symbol", "lastPrice", separator="")


def fetch_bybit() -> dict[str, Decimal]:
    return parse_bybit(_fetch_json(BYBIT_URL))


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
    print(f"SOURCE {label}: FETCHED")
    return value


def _show(section: str, item: str, values: dict[str, Decimal]) -> None:
    decision, ref, reason, accepted = consensus(item, values)
    all_values = ", ".join(f"{k}={v}" for k, v in sorted(values.items())) or "none"
    accepted_names = ",".join(sorted(accepted)) or "none"
    print(
        f"{section:<7} {item:<10} {decision:<10} reference="
        f"{ref if ref is not None else '—'} "
        f"accepted={accepted_names} all=[{all_values}]"
    )
    if decision != "VERIFIED":
        print(f"         reason: {reason}")


def run() -> None:
    print("READ-ONLY stage-3 probe: no sends, timers, database writes or config changes")

    print("\n===== 100 IQD / TOMAN =====")
    tgju_iqd = _safe("TGJU IQD", fetch_tgju_iqd100_toman)
    dolarchand_iqd = _safe("Dolarchand IQD", fetch_dolarchand_iqd100_toman)
    iqd: dict[str, Decimal] = {}
    if tgju_iqd is not None:
        iqd["tgju"] = tgju_iqd
    if dolarchand_iqd is not None:
        iqd["dolarchand"] = dolarchand_iqd
    _show("FX", "100 IQD", iqd)

    print("\n===== XAU / USD =====")
    tgju_xau = _safe("TGJU XAU", fetch_tgju_xau_usd)
    gold_api = _safe("Gold API XAU", fetch_gold_api_xau_usd)
    dolarchand_xau = _safe("Dolarchand XAU", fetch_dolarchand_xau_usd)
    xau: dict[str, Decimal] = {}
    if tgju_xau is not None:
        xau["tgju"] = tgju_xau
    if gold_api is not None:
        xau["gold-api"] = gold_api
    if dolarchand_xau is not None:
        xau["dolarchand"] = dolarchand_xau
    _show("GOLD", "XAU/USD", xau)
    print(
        "NOTE: production approval should prefer TGJU + an agreeing external "
        "provider; Gold API and Dolarchand upstream independence is not assumed."
    )

    print("\n===== CRYPTO / USDT DIRECT EXCHANGES =====")
    providers = {
        "okx": _safe("OKX", fetch_okx) or {},
        "gate": _safe("Gate", fetch_gate) or {},
        "kucoin": _safe("KuCoin", fetch_kucoin) or {},
        "bybit": _safe("Bybit", fetch_bybit) or {},
    }
    for symbol in CRYPTO_SYMBOLS:
        values = {
            provider: prices[symbol]
            for provider, prices in providers.items()
            if symbol in prices
        }
        _show("CRYPTO", symbol, values)


if __name__ == "__main__":
    run()
