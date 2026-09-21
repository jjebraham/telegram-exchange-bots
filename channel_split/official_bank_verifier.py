#!/usr/bin/env python3
"""Official-bank verification for selected Turkey bank FX rows."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ISBANK_URL = "https://www.isbank.com.tr/doviz-kurlari"
ZIRAAT_URL = "https://www.ziraatbank.com.tr/tr/fiyatlar-ve-oranlar"
KUVEYT_PORTAL_URL = "https://www.kuveytturk.com.tr/finans-portali"
GARANTI_CONFIG_URL = (
    "https://webforms.garantibbva.com.tr/"
    "currency-convertor-app-v3/config"
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_cell = False
        self._parts: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in {"td", "th"}:
            self._in_cell = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            value = " ".join("".join(self._parts).split())
            self._row.append(value)
            self._in_cell = False
            self._parts = []
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _number(value: str) -> Decimal | None:
    cleaned = value.strip().replace("\xa0", " ")
    match = re.search(r"(?<!\d)(\d{1,3}(?:[.]\d{3})*(?:,\d+)?|\d+(?:,\d+)?)(?!\d)", cleaned)
    if not match:
        return None
    token = match.group(1).replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(token)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _pair_code(pair: str) -> str:
    if pair == "USD/TRY":
        return "USD"
    if pair == "EUR/TRY":
        return "EUR"
    raise ValueError(f"Unsupported official bank pair: {pair}")


def _candidate_quotes(html: str, pair: str) -> list[tuple[Decimal, Decimal]]:
    code = _pair_code(pair)
    parser = _TableParser()
    parser.feed(html)

    candidates: list[tuple[Decimal, Decimal]] = []
    for row in parser.rows:
        code_index = next(
            (
                idx
                for idx, cell in enumerate(row)
                if cell.strip().upper() == code
                or cell.strip().upper().startswith(code + " ")
            ),
            None,
        )
        if code_index is None:
            continue

        numbers = [
            number
            for number in (_number(cell) for cell in row[code_index + 1 :])
            if number is not None
        ]
        if len(numbers) < 2:
            continue
        buy, sell = numbers[0], numbers[1]
        if sell <= buy:
            continue
        pair_value = (buy, sell)
        if pair_value not in candidates:
            candidates.append(pair_value)

    if not candidates:
        raise ValueError(f"Official bank page has no usable {code} buy/sell row")
    return candidates


def parse_isbank_quote(
    html: str,
    pair: str,
) -> tuple[Decimal, Decimal]:
    candidates = _candidate_quotes(html, pair)
    # Isbank's public page exposes one live bank buy/sell row per currency.
    return candidates[0]


def parse_isbank_midpoint(html: str, pair: str) -> Decimal:
    buy, sell = parse_isbank_quote(html, pair)
    return (buy + sell) / Decimal("2")


def parse_ziraat_quote(
    html: str,
    pair: str,
    *,
    primary_buy: Decimal,
    primary_sell: Decimal,
    max_mapping_deviation_pct: Decimal = Decimal("5.00"),
) -> tuple[Decimal, Decimal]:
    candidates = _candidate_quotes(html, pair)
    primary_buy = Decimal(str(primary_buy))
    primary_sell = Decimal(str(primary_sell))
    if primary_buy <= 0 or primary_sell <= 0 or primary_sell <= primary_buy:
        raise ValueError("Primary Ziraat quote must be positive and non-crossed")

    def mapping_deviation(
        candidate: tuple[Decimal, Decimal],
    ) -> Decimal:
        buy, sell = candidate
        buy_dev = abs(buy - primary_buy) / primary_buy * Decimal("100")
        sell_dev = abs(sell - primary_sell) / primary_sell * Decimal("100")
        return max(buy_dev, sell_dev)

    selected = min(candidates, key=mapping_deviation)
    deviation = mapping_deviation(selected)
    if deviation > max_mapping_deviation_pct:
        raise ValueError(
            "No Ziraat official rate channel matches the displayed row: "
            f"closest side deviation {deviation.quantize(Decimal('0.01'))}%"
        )
    return selected


def parse_ziraat_midpoint(
    html: str,
    pair: str,
    *,
    primary_midpoint: Decimal,
    max_mapping_deviation_pct: Decimal = Decimal("5.00"),
) -> Decimal:
    # Backwards-compatible helper for tests/diagnostics where only a midpoint
    # is available. Select by midpoint, while production uses parse_ziraat_quote
    # so both displayed sides are independently checked.
    candidates = _candidate_quotes(html, pair)
    primary = Decimal(str(primary_midpoint))
    if primary <= 0:
        raise ValueError("Primary Ziraat midpoint must be positive")
    midpoints = [(buy + sell) / Decimal("2") for buy, sell in candidates]
    selected = min(midpoints, key=lambda value: abs(value - primary))
    deviation = abs(selected - primary) / primary * Decimal("100")
    if deviation > max_mapping_deviation_pct:
        raise ValueError(
            "No Ziraat official rate channel matches the displayed row: "
            f"closest deviation {deviation.quantize(Decimal('0.01'))}%"
        )
    return selected


def parse_garanti_quote(
    payload: object,
    pair: str,
) -> tuple[Decimal, Decimal]:
    code = _pair_code(pair)

    def find_rows(value: object) -> list[object] | None:
        if isinstance(value, dict):
            rows = value.get("expandedCurrRateRespons")
            if isinstance(rows, list):
                return rows
            for child in value.values():
                found = find_rows(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find_rows(child)
                if found is not None:
                    return found
        return None

    rows = find_rows(payload)
    if rows is None:
        raise ValueError(
            "Garanti official response has no expandedCurrRateRespons"
        )

    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("currCode", "")).strip().upper() == code
        ),
        None,
    )
    if row is None:
        raise ValueError(
            f"Garanti official expanded-rate response is missing {code}"
        )

    try:
        buy = Decimal(str(row["exchBuyRate"]))
        sell = Decimal(str(row["exchSellRate"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            f"Garanti official {code} row has invalid "
            "exchBuyRate/exchSellRate"
        ) from exc

    if (
        not buy.is_finite()
        or not sell.is_finite()
        or buy <= 0
        or sell <= 0
        or sell <= buy
    ):
        raise ValueError(
            f"Garanti official {code} quote is invalid: "
            f"buy={buy} sell={sell}"
        )
    return buy, sell


def _find_string_by_key(payload: object, target_key: str) -> str:
    """Find a unique non-empty string value by key anywhere in JSON.

    Garanti has changed/wrapped the public config structure over time. The
    public app still identifies the service by the stable semantic key, so use
    that key rather than depending on one exact object nesting path.
    """
    matches: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key == target_key
                    and isinstance(child, str)
                    and child.strip()
                ):
                    matches.append(child.strip())
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)

    unique = list(dict.fromkeys(matches))
    if not unique:
        raise ValueError(
            f"Garanti config is missing {target_key}"
        )
    if len(unique) > 1:
        raise ValueError(
            f"Garanti config has multiple {target_key} values: "
            + ", ".join(unique[:3])
        )
    return unique[0]


def _discover_garanti_expanded_rate_url(timeout: int = 20) -> str:
    config = _fetch_json(GARANTI_CONFIG_URL, timeout)
    endpoint = _find_string_by_key(
        config,
        "expandedCurrRateServicePath",
    )
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "customers.garantibbva.com.tr"
    ):
        raise ValueError(
            "Garanti expanded-rate endpoint escaped official host: "
            f"{endpoint}"
        )
    return endpoint


def _fetch_json_post(
    url: str,
    payload: object,
    *,
    timeout: int = 20,
    origin: str | None = None,
    referer: str | None = None,
) -> object:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
        "Content-Type": "application/json",
        "User-Agent": "AlanChande-BankSafetyVerifier/1.0",
    }
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer

    request = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Official bank verifier returned HTTP {exc.code} "
            f"for {url}: {detail}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load official bank JSON verifier {url}: {exc}"
        ) from exc


def fetch_garanti_quote(
    pair: str,
    timeout: int = 20,
) -> tuple[Decimal, Decimal]:
    endpoint = _discover_garanti_expanded_rate_url(timeout)
    request_payload = {
        "parityParamName": "DOVIZ_PUBLIC",
        "parityParamAttrName": "CURRENCIES",
        "currCode": "",
        "currType": "A",
        "cdcFlag": "N",
        "latencyValue": 1800,
        "currTime": {
            "hour": 0,
            "minute": 0,
            "second": 0,
            "nano": 0,
        },
    }
    response = _fetch_json_post(
        endpoint,
        request_payload,
        timeout=timeout,
        origin="https://webforms.garantibbva.com.tr",
        referer=(
            "https://webforms.garantibbva.com.tr/"
            "currency-convertor-app-v3/"
        ),
    )
    return parse_garanti_quote(response, pair)


def parse_kuveyt_quote(
    payload: object,
    pair: str,
) -> tuple[Decimal, Decimal]:
    code = _pair_code(pair)
    if not isinstance(payload, list):
        raise ValueError("Kuveyt official exchange-rates response is not a list")

    row = next(
        (
            item
            for item in payload
            if isinstance(item, dict)
            and str(item.get("CurrencyCode", "")).strip().upper() == code
        ),
        None,
    )
    if row is None:
        raise ValueError(f"Kuveyt official exchange-rates response is missing {code}")

    try:
        buy = Decimal(str(row["BuyRate"]))
        sell = Decimal(str(row["SellRate"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            f"Kuveyt official {code} row has invalid BuyRate/SellRate"
        ) from exc

    if (
        not buy.is_finite()
        or not sell.is_finite()
        or buy <= 0
        or sell <= 0
        or sell <= buy
    ):
        raise ValueError(
            f"Kuveyt official {code} quote is invalid: buy={buy} sell={sell}"
        )
    return buy, sell


def _discover_kuveyt_exchange_rates_url(timeout: int = 20) -> str:
    html = _fetch_html(KUVEYT_PORTAL_URL, timeout)
    match = re.search(
        r"""<script[^>]+src=["']([^"']*magiclick\.core\.min\.js[^"']*)["']""",
        html,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Kuveyt finance portal does not expose magiclick.core")

    core_url = urljoin(KUVEYT_PORTAL_URL, match.group(1))
    javascript = _fetch_html(core_url, timeout)
    endpoint_match = re.search(
        r"""\bexchangeRates\s*:\s*["']([^"']+)["']""",
        javascript,
        re.IGNORECASE,
    )
    if not endpoint_match:
        raise ValueError("Kuveyt core script does not expose exchangeRates endpoint")

    endpoint = urljoin(KUVEYT_PORTAL_URL, endpoint_match.group(1))
    if not endpoint.startswith("https://www.kuveytturk.com.tr/"):
        raise ValueError(
            f"Kuveyt exchange-rates endpoint escaped official host: {endpoint}"
        )
    return endpoint


def _fetch_json(url: str, timeout: int = 20) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-BankSafetyVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"Official bank verifier returned HTTP {exc.code} for {url}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load official bank JSON verifier {url}: {exc}"
        ) from exc


def fetch_kuveyt_quote(
    pair: str,
    timeout: int = 20,
) -> tuple[Decimal, Decimal]:
    endpoint = _discover_kuveyt_exchange_rates_url(timeout)
    return parse_kuveyt_quote(_fetch_json(endpoint, timeout), pair)


def _fetch_html(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-BankSafetyVerifier/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(
            f"Official bank verifier returned HTTP {exc.code} for {url}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load official bank verifier {url}: {exc}") from exc


def fetch_isbank_quote(
    pair: str,
    timeout: int = 20,
) -> tuple[Decimal, Decimal]:
    return parse_isbank_quote(_fetch_html(ISBANK_URL, timeout), pair)


def fetch_isbank_midpoint(pair: str, timeout: int = 20) -> Decimal:
    buy, sell = fetch_isbank_quote(pair, timeout)
    return (buy + sell) / Decimal("2")


def fetch_ziraat_quote(
    pair: str,
    *,
    primary_buy: Decimal,
    primary_sell: Decimal,
    timeout: int = 20,
) -> tuple[Decimal, Decimal]:
    return parse_ziraat_quote(
        _fetch_html(ZIRAAT_URL, timeout),
        pair,
        primary_buy=primary_buy,
        primary_sell=primary_sell,
    )


def fetch_ziraat_midpoint(
    pair: str,
    *,
    primary_midpoint: Decimal,
    timeout: int = 20,
) -> Decimal:
    return parse_ziraat_midpoint(
        _fetch_html(ZIRAAT_URL, timeout),
        pair,
        primary_midpoint=primary_midpoint,
    )
