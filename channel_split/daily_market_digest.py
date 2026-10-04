#!/usr/bin/env python3
"""Verified once-daily Iran/global market digest for AlanChande.

The module deliberately separates collection, independent-source consensus,
fail-closed safety assessment, neutral display formatting, and 24h change
calculation from previously published verified digest values.

Fetching/building does not send Telegram messages and does not write history.
Production integration should record published values only after Telegram
delivery succeeds and the complete safety assessment is VERIFIED.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from hybrid_usdt_compare import collect_hybrid_usdt_snapshot
from iran_fx import fetch_iran_open_market_fx
from iran_gold import fetch_iran_gold_market, parse_tgju_profile_current
from iran_gold_external_verifier import fetch_dolarchand_iran_gold
from kiani_posts import JALALI_MONTHS, PERSIAN_WEEKDAYS, gregorian_to_jalali
from market_safety import (
    VERIFIED,
    PostSafetyAssessment,
    SafetyObservation,
    assess_post,
    usdt_source_family_values,
)
from rate_change_history import (
    load_published_values_near_age,
    percentage_changes,
)


TEHRAN_TZ = ZoneInfo("Asia/Tehran")

DOLARCHAND_FX_BASE = "https://dolarchand.com/en/currencies"
TGJU_IQD_URL = "https://www.tgju.org/profile/price_iqd"
DOLARCHAND_IQD_URL = "https://dolarchand.com/en/currencies/IQD-to-IRR"
TGJU_XAU_URL = "https://www.tgju.org/profile/ons"
DOLARCHAND_XAU_URL = "https://dolarchand.com/en/gold-silver/GOLD-OUNCE-to-IRR"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"

OKX_URL = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
GATE_URL = "https://api.gateio.ws/api/v4/spot/tickers"
KUCOIN_URL = "https://api.kucoin.com/api/v1/market/allTickers"
BITGET_URL = "https://api.bitget.com/api/v3/market/tickers?category=SPOT"

FX_CODES = ("USD", "EUR", "AED", "TRY", "CNY", "CAD", "AUD", "GBP", "AFN")
CRYPTO_SYMBOLS = ("BTC", "ETH", "BNB", "TRX", "SHIB", "ADA", "DOGE", "GRAM", "NOT", "SOL", "XRP")

FX_DISPLAY = (
    ("USD", "🇺🇸", "دلار آمریکا"),
    ("EUR", "🇪🇺", "یورو"),
    ("USDT", "💲", "تتر"),
    ("AED", "🇦🇪", "درهم"),
    ("TRY", "🇹🇷", "لیر ترکیه"),
    ("CNY", "🇨🇳", "یوان چین"),
    ("CAD", "🇨🇦", "دلار کانادا"),
    ("AUD", "🇦🇺", "دلار استرالیا"),
    ("GBP", "🇬🇧", "پوند انگلیس"),
    ("IQD100", "🇮🇶", "صد دینار عراق"),
    ("AFN", "🇦🇫", "افغانی"),
)
GOLD_DISPLAY = (
    ("COIN_EMAMI", "🌕", "سکه امامی (طرح جدید)"),
    ("COIN_AZADI", "🌕", "سکه بهار آزادی"),
    ("COIN_HALF", "🌕", "نیم سکه"),
    ("COIN_QUARTER", "🌕", "ربع سکه"),
    ("MESGHAL", "💫", "آبشده (مثقال طلا)"),
    ("GOLD18", "💫", "گرم طلای ۱۸ عیار"),
    ("XAUUSD", "💰", "انس طلا"),
)
CRYPTO_DISPLAY = (
    ("BTC", "₿", "بیت کوین"),
    ("ETH", "♦️", "اتریوم"),
    ("BNB", "🟡", "بایننس کوین"),
    ("TRX", "🟥", "ترون"),
    ("SHIB", "🐕", "شیبا"),
    ("ADA", "💧", "کاردانو"),
    ("DOGE", "🐶", "دوج‌کوین"),
    ("GRAM", "💎", "گرام (تون کوین)"),
    ("NOT", "❔", "نات کوین"),
    ("SOL", "🌞", "سولانا"),
    ("XRP", "💠", "ریپل"),
)

DAILY_DIGEST_EXPECTED_KEYS = frozenset(
    key
    for key, *_rest in (*FX_DISPLAY, *GOLD_DISPLAY, *CRYPTO_DISPLAY)
)
# These anchors define whether each major section is trustworthy enough to
# publish. Peripheral rows may be shown as unavailable without suppressing the
# entire 29-line digest.
DAILY_DIGEST_CORE_KEYS = frozenset(
    {"USD", "USDT", "COIN_EMAMI", "GOLD18", "BTC", "ETH"}
)
DAILY_DIGEST_MAX_UNAVAILABLE_NONCORE = 4

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


@dataclass(frozen=True)
class DailyDigestResult:
    text: str
    assessment: PostSafetyAssessment
    published_values: dict[str, Decimal]
    source_health: dict[str, str | None]


def _digest_key(market_key: str) -> str | None:
    prefix = "daily-digest:"
    if not market_key.startswith(prefix):
        return None
    return market_key[len(prefix):]


def _apply_partial_digest_policy(
    assessment: PostSafetyAssessment,
) -> tuple[PostSafetyAssessment, frozenset[str]]:
    check_by_key = {
        key: check
        for check in assessment.checks
        if (key := _digest_key(check.market_key))
    }

    # Never relax malformed/incomplete assessments.
    if frozenset(check_by_key) != DAILY_DIGEST_EXPECTED_KEYS:
        return assessment, frozenset()

    unavailable = frozenset(
        key
        for key, check in check_by_key.items()
        if check.decision != VERIFIED
    )
    if not unavailable:
        return assessment, frozenset()

    if unavailable & DAILY_DIGEST_CORE_KEYS:
        return assessment, unavailable

    if len(unavailable) > DAILY_DIGEST_MAX_UNAVAILABLE_NONCORE:
        return assessment, unavailable

    verified_count = sum(
        check.decision == VERIFIED
        for check in check_by_key.values()
    )
    if verified_count != len(DAILY_DIGEST_EXPECTED_KEYS) - len(unavailable):
        return assessment, unavailable

    details = "; ".join(
        f"{key}: {check_by_key[key].reason}"
        for key in sorted(unavailable)
    )
    return (
        PostSafetyAssessment(
            post_type=assessment.post_type,
            decision=VERIFIED,
            reason=(
                f"{verified_count}/{len(DAILY_DIGEST_EXPECTED_KEYS)} "
                "safety checks verified; omitted unavailable non-core rows: "
                f"{', '.join(sorted(unavailable))}; {details}"
            ),
            checks=assessment.checks,
        ),
        unavailable,
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
            "User-Agent": "AlanChande-DailyMarketDigest/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not load {url}: {type(exc).__name__}") from exc


def _fetch_json(url: str, *, timeout: int = 20) -> Any:
    try:
        return json.loads(_fetch_text(url, timeout=timeout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}") from exc


def parse_dolarchand_toman_rate(html: str) -> Decimal:
    text = _visible(html).translate(_DIGITS)
    patterns = (
        r"Sell rate for .*? to Toman\s+([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"about\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+Toman",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    raise ValueError("Dolarchand page has no parseable Toman rate")


def parse_dolarchand_iqd100_toman(html: str) -> Decimal:
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
    raise ValueError("Dolarchand page has no explicit 100-IQD Toman rate")


def parse_dolarchand_xau_usd(html: str) -> Decimal:
    text = _visible(html).translate(_DIGITS)
    patterns = (
        r"Sell rate for Gold Ounce \(Global\) to USD\s+"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"Gold Ounce \(Global\).*?([0-9][0-9,]*(?:\.[0-9]+)?)\s*USD",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    raise ValueError("Dolarchand page has no parseable XAU/USD rate")


def fetch_dolarchand_fx(code: str) -> Decimal:
    normalized = code.upper()
    if normalized not in FX_CODES:
        raise ValueError(f"Unsupported digest FX code: {code}")
    return parse_dolarchand_toman_rate(
        _fetch_text(f"{DOLARCHAND_FX_BASE}/{normalized}-to-IRR")
    )


def fetch_iqd_sources() -> dict[str, Decimal]:
    tgju = parse_tgju_profile_current(_fetch_text(TGJU_IQD_URL)) * Decimal("10")
    dolarchand = parse_dolarchand_iqd100_toman(_fetch_text(DOLARCHAND_IQD_URL))
    return {"tgju": tgju, "dolarchand": dolarchand}


def fetch_xau_sources() -> dict[str, Decimal]:
    tgju = parse_tgju_profile_current(_fetch_text(TGJU_XAU_URL))
    gold_payload = _fetch_json(GOLD_API_URL)
    if not isinstance(gold_payload, dict):
        raise ValueError("Gold API response is not an object")
    gold_api = _number(gold_payload.get("price"))
    dolarchand = parse_dolarchand_xau_usd(_fetch_text(DOLARCHAND_XAU_URL))
    return {
        "tgju": tgju,
        "gold-api": gold_api,
        "dolarchand": dolarchand,
    }


def _pairs(
    rows: list[dict[str, Any]],
    *,
    pair_key: str,
    price_key: str,
    separator: str,
) -> dict[str, Decimal]:
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


def fetch_okx_crypto() -> dict[str, Decimal]:
    payload = _fetch_json(OKX_URL)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected OKX ticker payload")
    return _pairs(
        payload["data"], pair_key="instId", price_key="last", separator="-"
    )


def fetch_gate_crypto() -> dict[str, Decimal]:
    payload = _fetch_json(GATE_URL)
    if not isinstance(payload, list):
        raise ValueError("Unexpected Gate ticker payload")
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


def fetch_kucoin_crypto() -> dict[str, Decimal]:
    payload = _fetch_json(KUCOIN_URL)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected KuCoin ticker payload")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("ticker"), list):
        raise ValueError("Unexpected KuCoin ticker data")
    return _pairs(
        data["ticker"], pair_key="symbol", price_key="last", separator="-"
    )


def fetch_bitget_crypto() -> dict[str, Decimal]:
    payload = _fetch_json(BITGET_URL)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected Bitget ticker payload")
    return _pairs(
        payload["data"], pair_key="symbol", price_key="lastPrice", separator=""
    )


def _safe_fetch(
    health: dict[str, str | None],
    key: str,
    fetcher: Any,
    fallback: Any,
) -> Any:
    try:
        value = fetcher()
    except Exception as exc:
        health[key] = f"{type(exc).__name__}: {exc}"[:300]
        return fallback
    health[key] = None
    return value


def _gold_sources(
    market: Any,
    dolarchand: Mapping[str, Decimal],
) -> dict[str, dict[str, Decimal]]:
    mapping = {
        "COIN_EMAMI": ("سکه امامی", market.coin_prices_rial.get("سکه امامی")),
        "COIN_AZADI": ("سکه بهار آزادی", market.coin_prices_rial.get("سکه بهار آزادی")),
        "COIN_HALF": ("نیم سکه", market.coin_prices_rial.get("نیم سکه")),
        "COIN_QUARTER": ("ربع سکه", market.coin_prices_rial.get("ربع سکه")),
        "MESGHAL": ("مثقال طلا", market.mesghal_rial),
        "GOLD18": ("طلای ۱۸ عیار", market.gold18_rial),
    }
    sources: dict[str, dict[str, Decimal]] = {}
    for key, (label, raw_rial) in mapping.items():
        values: dict[str, Decimal] = {}
        if raw_rial is not None:
            values["tgju"] = Decimal(str(raw_rial)) / Decimal("10")
        if label in dolarchand:
            values["dolarchand"] = Decimal(str(dolarchand[label]))
        sources[key] = values
    return sources


def collect_digest(
    history_db: Path,
    *,
    now: datetime | None = None,
) -> DailyDigestResult:
    """Fetch, verify and format the complete 29-line digest."""
    health: dict[str, str | None] = {}

    tgju_fx = _safe_fetch(health, "iran:tgju-fx", fetch_iran_open_market_fx, {})
    dolarchand_fx: dict[str, Decimal] = {}
    for code in FX_CODES:
        value = _safe_fetch(
            health,
            f"iran:dolarchand-fx:{code}",
            lambda code=code: fetch_dolarchand_fx(code),
            None,
        )
        if value is not None:
            dolarchand_fx[code] = value

    hybrid = _safe_fetch(
        health,
        "iran:hybrid-usdt",
        collect_hybrid_usdt_snapshot,
        None,
    )
    usdt_families: dict[str, Decimal] = {}
    if hybrid is not None:
        usdt_families = usdt_source_family_values(hybrid.quotes)
        for source_key, error in hybrid.source_health.items():
            health[source_key] = error

    iqd_sources = _safe_fetch(health, "iran:iqd-pair", fetch_iqd_sources, {})

    tgju_gold = _safe_fetch(health, "iran:tgju-gold", fetch_iran_gold_market, None)
    dolarchand_gold = _safe_fetch(
        health,
        "iran:dolarchand-gold",
        lambda: fetch_dolarchand_iran_gold(max_age_minutes=120),
        {},
    )
    gold_sources: dict[str, dict[str, Decimal]] = {}
    if tgju_gold is not None:
        gold_sources = _gold_sources(tgju_gold, dolarchand_gold)

    xau_sources = _safe_fetch(health, "global:xau", fetch_xau_sources, {})

    crypto_providers = {
        "okx": _safe_fetch(health, "crypto:okx", fetch_okx_crypto, {}),
        "gate": _safe_fetch(health, "crypto:gate", fetch_gate_crypto, {}),
        "kucoin": _safe_fetch(health, "crypto:kucoin", fetch_kucoin_crypto, {}),
        "bitget": _safe_fetch(health, "crypto:bitget", fetch_bitget_crypto, {}),
    }

    observations: list[SafetyObservation] = []
    for code in FX_CODES:
        values: dict[str, Decimal] = {}
        if code in tgju_fx:
            values["tgju"] = Decimal(str(tgju_fx[code]))
        if code in dolarchand_fx:
            values["dolarchand"] = Decimal(str(dolarchand_fx[code]))
        observations.append(
            SafetyObservation(
                market_key=f"daily-digest:{code}",
                source_values=values,
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("6.00"),
                # TGJU + Dolarchand are the only independent families for
                # these digest FX rows. Requiring a third source makes a
                # large-move recovery impossible after any blocked day.
                strong_quorum=2,
            )
        )

    observations.append(
        SafetyObservation(
            market_key="daily-digest:USDT",
            source_values=usdt_families,
            min_sources=2,
            max_source_deviation_pct=Decimal("2.00"),
            suspicious_move_pct=Decimal("5.00"),
            strong_quorum=3,
        )
    )
    observations.append(
        SafetyObservation(
            market_key="daily-digest:IQD100",
            source_values=iqd_sources,
            min_sources=2,
            max_source_deviation_pct=Decimal("2.00"),
            suspicious_move_pct=Decimal("6.00"),
            # IQD100 has exactly TGJU + Dolarchand.
            strong_quorum=2,
        )
    )

    for key, _flag, _label in GOLD_DISPLAY[:-1]:
        observations.append(
            SafetyObservation(
                market_key=f"daily-digest:{key}",
                source_values=gold_sources.get(key, {}),
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("7.00"),
                # Iran gold digest rows have exactly TGJU + Dolarchand.
                strong_quorum=2,
            )
        )

    observations.append(
        SafetyObservation(
            market_key="daily-digest:XAUUSD",
            source_values=xau_sources,
            min_sources=2,
            max_source_deviation_pct=Decimal("2.00"),
            suspicious_move_pct=Decimal("5.00"),
            strong_quorum=3,
        )
    )

    for symbol in CRYPTO_SYMBOLS:
        values = {
            provider: prices[symbol]
            for provider, prices in crypto_providers.items()
            if symbol in prices
        }
        observations.append(
            SafetyObservation(
                market_key=f"daily-digest:{symbol}",
                source_values=values,
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("12.00"),
                strong_quorum=3,
            )
        )

    assessment = assess_post(history_db, "daily-market-digest", observations)
    assessment, unavailable_keys = _apply_partial_digest_policy(assessment)

    current: dict[str, Decimal] = {}
    for check in assessment.checks:
        if check.decision != VERIFIED or check.reference_value is None:
            continue
        key = check.market_key.removeprefix("daily-digest:")
        current[key] = check.reference_value

    previous = load_published_values_near_age(
        history_db,
        "daily-digest",
        target_hours=24,
        min_age_hours=18,
        max_age_hours=30,
        now=now,
    )
    changes = percentage_changes(current, previous)
    text = build_digest_post(
        current,
        changes,
        now=now,
        unavailable_keys=unavailable_keys,
    )
    return DailyDigestResult(
        text=text,
        assessment=assessment,
        published_values=current,
        source_health=health,
    )


def _fmt_toman(key: str, value: Decimal) -> str:
    quantum = Decimal("1")
    if key in {"USD", "EUR", "USDT", "AED", "CNY", "CAD", "AUD", "GBP", "IQD100"}:
        quantum = Decimal("1E1")
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{int(rounded):,}"


def _fmt_crypto(key: str, value: Decimal) -> str:
    decimals = {
        "BTC": 2,
        "ETH": 2,
        "BNB": 2,
        "TRX": 5,
        "SHIB": 9,
        "ADA": 4,
        "DOGE": 5,
        "GRAM": 4,
        "NOT": 7,
        "SOL": 2,
        "XRP": 4,
    }[key]
    rendered = f"{value:,.{decimals}f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _fmt_change(value: Decimal | None) -> str:
    if value is None:
        return "➖ —"
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded > 0:
        return f"🔼 %{abs(rounded):.2f}"
    if rounded < 0:
        return f"🔻 %{abs(rounded):.2f}"
    return "➖ %0.00"


def _digest_date(now: datetime | None = None) -> tuple[str, str]:
    local = (now or datetime.now(TEHRAN_TZ)).astimezone(TEHRAN_TZ)
    _jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    weekday = PERSIAN_WEEKDAYS[local.weekday()]
    return f"{weekday} {jd} {JALALI_MONTHS[jm]}", local.strftime("%H:%M")


def build_digest_post(
    values: Mapping[str, Decimal],
    changes_24h: Mapping[str, Decimal] | None = None,
    *,
    now: datetime | None = None,
    unavailable_keys: set[str] | frozenset[str] | tuple[str, ...] = (),
) -> str:
    unavailable = set(unavailable_keys)
    unknown_unavailable = sorted(unavailable - DAILY_DIGEST_EXPECTED_KEYS)
    if unknown_unavailable:
        raise ValueError(
            "Daily digest has unknown unavailable keys: "
            + ", ".join(unknown_unavailable)
        )

    missing = sorted(
        DAILY_DIGEST_EXPECTED_KEYS - set(values) - unavailable
    )
    if missing:
        raise ValueError("Daily digest is missing: " + ", ".join(missing))

    changes = changes_24h or {}
    date_text, time_text = _digest_date(now)

    lines = [
        f"📆 <b>{date_text}</b>    🕰 <b>{time_text}</b>",
        "",
        "💱 <b>نرخ ارز:</b> (تومان)",
    ]
    for key, flag, label in FX_DISPLAY:
        if key in unavailable:
            lines.append(
                f"{flag} <b>{label}</b> <code>—</code> ➖ —"
            )
            continue
        lines.append(
            f"{flag} <b>{label}</b> <code>{_fmt_toman(key, values[key])}</code> "
            f"{_fmt_change(changes.get(key))}"
        )

    lines.extend(["", "🪙 <b>قیمت طلا و سکه:</b> (تومان)"])
    for key, flag, label in GOLD_DISPLAY:
        if key in unavailable:
            lines.append(
                f"{flag} <b>{label}</b> <code>—</code> ➖ —"
            )
        elif key == "XAUUSD":
            xau = values[key].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lines.append(
                f"{flag} <b>{label}</b> <code>{xau:,}$</code> "
                f"{_fmt_change(changes.get(key))}"
            )
        else:
            lines.append(
                f"{flag} <b>{label}</b> <code>{_fmt_toman(key, values[key])}</code> "
                f"{_fmt_change(changes.get(key))}"
            )

    lines.extend(["", "🧬 <b>رمزارزها:</b> (دلار)"])
    for key, flag, label in CRYPTO_DISPLAY:
        if key in unavailable:
            lines.append(
                f"{flag} <b>{label}</b> ({key}) <code>—</code> ➖ —"
            )
            continue
        lines.append(
            f"{flag} <b>{label}</b> ({key}) "
            f"<code>{_fmt_crypto(key, values[key])}$</code> "
            f"{_fmt_change(changes.get(key))}"
        )

    if unavailable:
        label_by_key = {
            key: label
            for key, _flag, label in (
                *FX_DISPLAY,
                *GOLD_DISPLAY,
                *CRYPTO_DISPLAY,
            )
        }
        unavailable_labels = "، ".join(
            label_by_key[key] for key in sorted(unavailable)
        )
        lines.extend(
            [
                "",
                "⚠️ برخی نرخ‌ها به‌دلیل اختلاف یا کمبود منابع "
                f"موقتاً نمایش داده نمی‌شوند: {unavailable_labels}",
            ]
        )

    lines.extend(["", "🔗 @alanchande_com"])
    text = "\n".join(lines)
    if len(text) > 4096:
        raise ValueError(f"Daily digest exceeds Telegram limit: {len(text)} chars")
    return text
