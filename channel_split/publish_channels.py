#!/usr/bin/env python3
"""Publish AlanChande information posts and Kiani transaction posts.

Each brand can use its own Telegram bot and its own destination channel. Channel
IDs/usernames and bot tokens are environment variables, so we can test against
two throw-away channels first and later move to production without code changes.
A local channel_split/.env file is loaded automatically when present.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from aggregator_bank_verifier import fetch_canlidoviz_garanti_quote
from altinkaynak_verifier import (
    fetch_altinkaynak_currency_quotes,
    fetch_altinkaynak_gold_quotes,
)
from bank_compare import (
    build_eur_comparison_post,
    build_usd_comparison_post,
    fetch_eur_comparison,
    fetch_usd_comparison,
)
from gold_prices import build_turkish_gold_post, fetch_turkish_gold_quotes
from gold_history import load_turkey_gold_near_24h, record_turkey_gold_quotes
from iran_gold import build_iran_gold_post, fetch_iran_gold_market
from iran_gold_external_verifier import fetch_dolarchand_iran_gold
from iran_gold_history import load_iran_gold_near_24h, record_iran_gold_market
from iran_fx import build_iran_fx_post, fetch_iran_open_market_fx
from iran_fx_adonis import fetch_adonis_try_sell_toman
from iran_fx_pashizi import fetch_pashizi_iran_fx
from iran_usdt import build_usdt_exchange_post, fetch_usdt_exchange_quotes
from kiani_shared_pricing import (
    calculate_kiani_rates,
    fetch_btcturk_usdt_try,
    load_shared_adjustments,
)
from kiani_posts import (
    build_kiani_rate_post,
    build_kiani_toman_receive_post,
    build_kiani_try_post,
    build_kiani_try_receive_post,
)
from nobitex_usdt import build_nobitex_usdt_post, fetch_nobitex_usdt
from wallex_usdt import build_wallex_usdt_post, fetch_wallex_usdt
from tabdeal_usdt import build_tabdeal_usdt_post, fetch_tabdeal_usdt
from exir_usdt import build_exir_usdt_post, fetch_exir_usdt
from bitpin_usdt import build_bitpin_usdt_post, fetch_bitpin_usdt
from ramzinex_usdt import build_ramzinex_usdt_post, fetch_ramzinex_usdt
from abantether_usdt import build_abantether_usdt_post, fetch_abantether_usdt
from tetherland_usdt import build_tetherland_usdt_post, fetch_tetherland_usdt
from direct_usdt_compare import fetch_and_build_direct_usdt_comparison
from hybrid_usdt_compare import (
    build_hybrid_usdt_post,
    collect_hybrid_usdt_snapshot,
    fetch_and_build_hybrid_usdt_post,
)
from market_pulse import build_turkey_fx_pulse_post
from official_bank_verifier import (
    fetch_garanti_quote,
    fetch_isbank_quote,
    fetch_kuveyt_quote,
    fetch_ziraat_quote,
)
from daily_market_digest import collect_digest
from admin_alerts import maybe_notify_admin, maybe_notify_source_health
from market_safety import (
    VERIFIED,
    PostSafetyAssessment,
    SafetyObservation,
    SourceHealthEvent,
    assess_post,
    bank_fx_observations,
    fx_pulse_observations,
    iran_gold_observations,
    normalize_mode,
    publication_allowed,
    recent_safety_status,
    recent_source_health_status,
    record_assessment,
    record_source_health_event,
    turkey_gold_observations,
    usdt_observations,
)
from market_history import (
    DEFAULT_HISTORY_DB,
    build_alanchande_daily_change_post,
    build_snapshot,
    history_status,
    load_bank_fx_near_24h,
    load_day,
    record_bank_fx_quotes,
    record_snapshot,
)
from rate_change_history import (
    load_published_values_near_age,
    percentage_changes,
    record_published_values,
)

DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def _load_local_env() -> None:
    """Load channel_split/.env without adding a third-party dependency."""
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _positive_decimal(value: Any, key: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Rate {key!r} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Rate {key!r} must be positive")
    return parsed


def fetch_kiani_rates(
    url: str = DEFAULT_RATES_URL,
    timeout: int = 20,
    retries: int = 3,
) -> dict[str, Decimal]:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Kiani-TelegramPublisher/1.4"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except HTTPError as exc:
            last_error = exc
            if exc.code in {502, 503, 504} and attempt < retries:
                time.sleep(attempt)
                continue
            raise RuntimeError(f"Kiani rates API returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(attempt)
                continue
            raise RuntimeError(f"Could not load Kiani rates: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not decode Kiani rates response: {exc}") from exc

        raw = payload.get("rates") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise ValueError("Kiani rates API response has no rates object")

        keys = ("buy_lira", "sell_lira", "buy_usdt", "sell_usdt", "lira_to_usdt", "usdt_to_lira")
        missing = [key for key in keys if key not in raw]
        if missing:
            raise ValueError("Missing Kiani rates: " + ", ".join(missing))
        return {key: _positive_decimal(raw[key], key) for key in keys}

    raise RuntimeError(f"Could not load Kiani rates: {last_error}")


def _fmt_int(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_cross(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}".rstrip("0").rstrip(".")


def _now_text() -> str:
    return datetime.now(ISTANBUL_TZ).strftime("%H:%M")


def _history_db_path() -> Path:
    configured = os.environ.get("MARKET_HISTORY_DB", "").strip()
    if not configured:
        return DEFAULT_HISTORY_DB
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def build_default_alanchande_usdt_post() -> str:
    """Build the production AlanChande USDT board using the seven-exchange hybrid."""
    return fetch_and_build_hybrid_usdt_post()


def build_alanchande_converter_post(rates: dict[str, Decimal]) -> str:
    sell_try = rates["buy_lira"]
    amounts = (
        ("یک میلیون", Decimal("1000000")),
        ("ده میلیون", Decimal("10000000")),
        ("پنجاه میلیون", Decimal("50000000")),
        ("صد میلیون", Decimal("100000000")),
    )
    lines = [
        "💰 <b>الان چند میشه؟</b>",
        "",
        "تبدیل تومان به لیر با نرخ فعلی:",
        "",
    ]
    for label, toman in amounts:
        try_amount = toman / sell_try
        lines.append(f"🇹🇷 {label} تومان ≈ <b>{_fmt_int(try_amount)}</b> لیر")
    lines.extend(
        [
            "",
            f"نرخ محاسبه: هر ۱ لیر = <b>{_fmt_int(sell_try)}</b> تومان",
            f"🕒 {_now_text()} استانبول",
        ]
    )
    return "\n".join(lines)


def build_alanchande_snapshot_post(rates: dict[str, Decimal], quotes: list[Any]) -> str:
    kapali = next((q for q in quotes if q.name == "Kapalıçarşı"), None)
    if kapali is None:
        raise ValueError("Kapalıçarşı quote is required for market snapshot")

    return "\n".join(
        [
            "📊 <b>نبض بازار | الان چنده؟</b>",
            "",
            f"🇹🇷 لیر: <b>{_fmt_int(rates['buy_lira'])}</b> تومان",
            f"🪙 تتر: <b>{_fmt_int(rates['buy_usdt'])}</b> تومان",
            f"💵 دلار/لیر بازار: <b>{_fmt_cross(kapali.buy)}</b> | <b>{_fmt_cross(kapali.sell)}</b>",
            f"🔄 تتر/لیر: <b>{_fmt_cross(rates['lira_to_usdt'])}</b> لیر",
            "",
            f"🕒 {_now_text()} استانبول",
        ]
    )


def build_resilient_market_bundle(
    builders: list[tuple[str, Callable[[], str]]],
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Build independent AlanChande market posts without one failure killing all."""
    posts: list[tuple[str, str]] = []
    failures: dict[str, str] = {}

    for key, builder in builders:
        try:
            posts.append((key, builder()))
        except Exception as exc:
            failures[key] = f"{type(exc).__name__}: {exc}"[:300]

    return posts, failures


def telegram_send(token: str, chat_id: str, text: str, timeout: int = 20) -> dict[str, Any]:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "disable_notification": "true",
        }
    ).encode("utf-8")
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Telegram request failed: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def main() -> int:
    _load_local_env()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--post",
        choices=(
            "bank-comparison",
            "eur-bank-comparison",
            "bank-comparisons",
            "alanchande-converter",
            "alanchande-snapshot",
            "alanchande-daily-change",
            "alanchande-fx-pulse",
            "alanchande-iran-fx",
            "alanchande-turkey-gold",
            "alanchande-iran-gold",
            "alanchande-usdt-exchanges",
            "alanchande-usdt-nobitex",
            "alanchande-usdt-wallex",
            "alanchande-usdt-tabdeal",
            "alanchande-usdt-exir",
            "alanchande-usdt-bitpin",
            "alanchande-usdt-ramzinex",
            "alanchande-usdt-abantether",
            "alanchande-usdt-tetherland",
            "alanchande-usdt-direct",
            "alanchande-usdt-tgju",
            "alanchande-usdt-seven",
            "alanchande-markets",
            "alanchande-daily",
            "alanchande-daily-digest",
            "kiani-rates",
            "kiani-try",
            "kiani-examples",
            "kiani-examples-reverse",
            "demo-formats",
            "all",
        ),
        default="all",
        help="Which split-channel post to build/send",
    )
    history_actions = parser.add_mutually_exclusive_group()
    history_actions.add_argument(
        "--record-history",
        action="store_true",
        help="Fetch neutral market data, store one local SQLite snapshot, then exit",
    )
    history_actions.add_argument(
        "--history-status",
        action="store_true",
        help="Show how many market snapshots are stored for today, then exit",
    )
    history_actions.add_argument(
        "--safety-status",
        action="store_true",
        help="Show recent market-safety audit decisions, then exit",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print posts instead of sending to Telegram")
    args = parser.parse_args()

    # (token_env, destination_env, text, post_key, safety_assessment)
    jobs: list[
        tuple[str, str, str, str | None, PostSafetyAssessment | None]
    ] = []
    sent_market_posts: set[str] = set()
    verified_sent_market_posts: set[str] = set()
    daily_digest_cache: Any | None = None
    daily_digest_publish_cache: dict[str, Decimal] | None = None
    rates_cache: dict[str, Decimal] | None = None
    usd_quotes_cache: list[Any] | None = None
    eur_quotes_cache: list[Any] | None = None
    turkey_gold_cache: list[Any] | None = None
    iran_fx_cache: dict[str, Decimal] | None = None
    iran_fx_external_cache: dict[str, Decimal] | None = None
    iran_fx_external_attempted = False
    iran_fx_external_error: str | None = None
    iran_fx_adonis_try_cache: Decimal | None = None
    iran_fx_adonis_attempted = False
    iran_fx_adonis_error: str | None = None
    iran_fx_publish_cache: dict[str, Decimal] | None = None
    iran_gold_cache: Any | None = None
    iran_gold_external_cache: dict[str, Decimal] | None = None
    iran_gold_external_attempted = False
    iran_gold_external_error: str | None = None
    iran_usdt_cache: list[Any] | None = None
    nobitex_usdt_cache: Any | None = None
    wallex_usdt_cache: Any | None = None
    tabdeal_usdt_cache: Any | None = None
    exir_usdt_cache: Any | None = None
    bitpin_usdt_cache: Any | None = None
    ramzinex_usdt_cache: Any | None = None
    abantether_usdt_cache: Any | None = None
    tetherland_usdt_cache: Any | None = None
    hybrid_usdt_cache: list[Any] | None = None
    source_health_events: dict[str, SourceHealthEvent] = {}
    altinkaynak_currency_cache: dict[
        str, tuple[Decimal, Decimal]
    ] | None = None
    altinkaynak_currency_attempted = False
    altinkaynak_currency_error: str | None = None
    altinkaynak_gold_cache: dict[
        str, tuple[Decimal, Decimal]
    ] | None = None
    altinkaynak_gold_attempted = False
    altinkaynak_gold_error: str | None = None
    official_bank_cache: dict[
        str, dict[str, tuple[Decimal, Decimal]]
    ] = {}
    official_bank_errors: dict[str, dict[str, str]] = {}

    def note_source_health(
        source_key: str,
        healthy: bool,
        detail: str = "",
    ) -> None:
        source_health_events[source_key] = SourceHealthEvent(
            source_key=source_key,
            healthy=healthy,
            detail=detail[:500],
        )

    def get_rates() -> dict[str, Decimal]:
        nonlocal rates_cache
        if rates_cache is None:
            quotes = get_hybrid_usdt()
            buy_values = sorted(
                Decimal(str(quote.buy_toman))
                for quote in quotes
            )
            if not buy_values:
                raise RuntimeError("No verified USDT/Toman market values for Kiani pricing")
            middle = len(buy_values) // 2
            if len(buy_values) % 2:
                market_usdt_toman = buy_values[middle]
            else:
                market_usdt_toman = (
                    buy_values[middle - 1] + buy_values[middle]
                ) / Decimal("2")

            try:
                market_usdt_try = fetch_btcturk_usdt_try()
                note_source_health("kiani:btcturk-usdttry", True)
            except Exception as exc:
                note_source_health(
                    "kiani:btcturk-usdttry",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise

            try:
                adjustments = load_shared_adjustments()
                note_source_health("kiani:shared-pricing-db", True)
            except Exception as exc:
                note_source_health(
                    "kiani:shared-pricing-db",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise

            rates_cache = calculate_kiani_rates(
                market_usdt_toman,
                market_usdt_try,
                adjustments,
            )
        return rates_cache

    def get_usd_quotes() -> list[Any]:
        nonlocal usd_quotes_cache
        if usd_quotes_cache is None:
            try:
                usd_quotes_cache = fetch_usd_comparison()
                note_source_health("turkey:doviz-usd", True)
            except Exception as exc:
                note_source_health(
                    "turkey:doviz-usd",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise
        return usd_quotes_cache

    def get_eur_quotes() -> list[Any]:
        nonlocal eur_quotes_cache
        if eur_quotes_cache is None:
            try:
                eur_quotes_cache = fetch_eur_comparison()
                note_source_health("turkey:doviz-eur", True)
            except Exception as exc:
                note_source_health(
                    "turkey:doviz-eur",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise
        return eur_quotes_cache

    def get_turkey_gold() -> list[Any]:
        nonlocal turkey_gold_cache
        if turkey_gold_cache is None:
            try:
                turkey_gold_cache = fetch_turkish_gold_quotes()
                note_source_health("turkey:doviz-gold", True)
            except Exception as exc:
                note_source_health(
                    "turkey:doviz-gold",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise
        return turkey_gold_cache

    def get_iran_fx() -> dict[str, Decimal]:
        nonlocal iran_fx_cache
        if iran_fx_cache is None:
            try:
                iran_fx_cache = fetch_iran_open_market_fx()
                note_source_health(
                    "iran:tgju-fx",
                    True,
                    "parsed 25 free-market currency rows",
                )
            except Exception as exc:
                note_source_health(
                    "iran:tgju-fx",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise
        return iran_fx_cache

    def _iran_fx_external_max_age_minutes() -> int:
        try:
            value = int(
                os.environ.get(
                    "IRAN_FX_EXTERNAL_MAX_AGE_MINUTES",
                    "900",
                )
            )
        except ValueError:
            value = 900
        return max(value, 1)

    def get_iran_fx_external_safe() -> dict[str, Decimal]:
        nonlocal iran_fx_external_cache
        nonlocal iran_fx_external_attempted
        nonlocal iran_fx_external_error

        if not iran_fx_external_attempted:
            iran_fx_external_attempted = True
            try:
                iran_fx_external_cache = fetch_pashizi_iran_fx(
                    max_age_minutes=_iran_fx_external_max_age_minutes()
                )
                note_source_health("iran:pashizi-fx", True)
            except Exception as exc:
                iran_fx_external_cache = {}
                iran_fx_external_error = (
                    f"pashizi-fx: {type(exc).__name__}: {exc}"
                )[:240]
                note_source_health(
                    "iran:pashizi-fx",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                print(
                    f"WARNING: Pashizi Iran-FX verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        return iran_fx_external_cache or {}

    def get_iran_fx_adonis_try_safe() -> Decimal | None:
        nonlocal iran_fx_adonis_try_cache
        nonlocal iran_fx_adonis_attempted
        nonlocal iran_fx_adonis_error

        if not iran_fx_adonis_attempted:
            iran_fx_adonis_attempted = True
            try:
                iran_fx_adonis_try_cache = fetch_adonis_try_sell_toman()
                note_source_health("iran:adonis-try", True)
            except Exception as exc:
                iran_fx_adonis_try_cache = None
                iran_fx_adonis_error = (
                    f"adonis-try: {type(exc).__name__}: {exc}"
                )[:240]
                note_source_health(
                    "iran:adonis-try",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                print(
                    f"WARNING: Adonis TRY verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        return iran_fx_adonis_try_cache

    def get_iran_gold() -> Any:
        nonlocal iran_gold_cache
        if iran_gold_cache is None:
            try:
                iran_gold_cache = fetch_iran_gold_market()
                note_source_health("iran:tgju-gold", True)
            except Exception as exc:
                note_source_health(
                    "iran:tgju-gold",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                raise
        return iran_gold_cache

    def _iran_gold_external_max_age_minutes() -> int:
        try:
            value = int(
                os.environ.get(
                    "IRAN_GOLD_EXTERNAL_MAX_AGE_MINUTES",
                    "240",
                )
            )
        except ValueError:
            value = 240
        return max(value, 1)

    def get_iran_gold_external_safe() -> dict[str, Decimal]:
        nonlocal iran_gold_external_cache
        nonlocal iran_gold_external_attempted
        nonlocal iran_gold_external_error

        if not iran_gold_external_attempted:
            iran_gold_external_attempted = True
            try:
                iran_gold_external_cache = fetch_dolarchand_iran_gold(
                    max_age_minutes=_iran_gold_external_max_age_minutes()
                )
                note_source_health("iran:dolarchand-gold", True)
            except Exception as exc:
                iran_gold_external_cache = {}
                iran_gold_external_error = (
                    f"dolarchand-gold: {type(exc).__name__}: {exc}"
                )[:240]
                note_source_health(
                    "iran:dolarchand-gold",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                print(
                    f"WARNING: Dolarchand Iran-gold verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        return iran_gold_external_cache or {}

    def get_iran_usdt() -> list[Any]:
        nonlocal iran_usdt_cache
        if iran_usdt_cache is None:
            iran_usdt_cache = fetch_usdt_exchange_quotes()
        return iran_usdt_cache

    def get_nobitex_usdt() -> Any:
        nonlocal nobitex_usdt_cache
        if nobitex_usdt_cache is None:
            nobitex_usdt_cache = fetch_nobitex_usdt()
        return nobitex_usdt_cache

    def get_wallex_usdt() -> Any:
        nonlocal wallex_usdt_cache
        if wallex_usdt_cache is None:
            wallex_usdt_cache = fetch_wallex_usdt()
        return wallex_usdt_cache

    def get_tabdeal_usdt() -> Any:
        nonlocal tabdeal_usdt_cache
        if tabdeal_usdt_cache is None:
            tabdeal_usdt_cache = fetch_tabdeal_usdt()
        return tabdeal_usdt_cache

    def get_exir_usdt() -> Any:
        nonlocal exir_usdt_cache
        if exir_usdt_cache is None:
            exir_usdt_cache = fetch_exir_usdt()
        return exir_usdt_cache

    def get_bitpin_usdt() -> Any:
        nonlocal bitpin_usdt_cache
        if bitpin_usdt_cache is None:
            bitpin_usdt_cache = fetch_bitpin_usdt()
        return bitpin_usdt_cache

    def get_ramzinex_usdt() -> Any:
        nonlocal ramzinex_usdt_cache
        if ramzinex_usdt_cache is None:
            ramzinex_usdt_cache = fetch_ramzinex_usdt()
        return ramzinex_usdt_cache

    def get_abantether_usdt() -> Any:
        nonlocal abantether_usdt_cache
        if abantether_usdt_cache is None:
            abantether_usdt_cache = fetch_abantether_usdt()
        return abantether_usdt_cache

    def get_tetherland_usdt() -> Any:
        nonlocal tetherland_usdt_cache
        if tetherland_usdt_cache is None:
            tetherland_usdt_cache = fetch_tetherland_usdt()
        return tetherland_usdt_cache

    def get_hybrid_usdt() -> list[Any]:
        nonlocal hybrid_usdt_cache
        if hybrid_usdt_cache is None:
            snapshot = collect_hybrid_usdt_snapshot()
            hybrid_usdt_cache = snapshot.quotes
            for source_key, error in snapshot.source_health.items():
                note_source_health(
                    source_key,
                    error is None,
                    error or "",
                )
        return hybrid_usdt_cache

    def _altinkaynak_max_age_minutes() -> int:
        try:
            value = int(os.environ.get("ALTINKAYNAK_MAX_AGE_MINUTES", "90"))
        except ValueError:
            value = 90
        return max(value, 1)

    def get_altinkaynak_currency_safe() -> dict[
        str, tuple[Decimal, Decimal]
    ]:
        nonlocal altinkaynak_currency_cache
        nonlocal altinkaynak_currency_attempted
        nonlocal altinkaynak_currency_error
        if not altinkaynak_currency_attempted:
            altinkaynak_currency_attempted = True
            try:
                altinkaynak_currency_cache = fetch_altinkaynak_currency_quotes(
                    max_age_minutes=_altinkaynak_max_age_minutes()
                )
                note_source_health("turkey:altinkaynak-currency", True)
            except Exception as exc:
                altinkaynak_currency_cache = {}
                note_source_health(
                    "turkey:altinkaynak-currency",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                altinkaynak_currency_error = (
                    f"altinkaynak-currency: {type(exc).__name__}: {exc}"
                )[:240]
                print(
                    f"WARNING: Altinkaynak currency verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        return altinkaynak_currency_cache or {}

    def get_altinkaynak_gold_safe() -> dict[
        str, tuple[Decimal, Decimal]
    ]:
        nonlocal altinkaynak_gold_cache
        nonlocal altinkaynak_gold_attempted
        nonlocal altinkaynak_gold_error
        if not altinkaynak_gold_attempted:
            altinkaynak_gold_attempted = True
            try:
                altinkaynak_gold_cache = fetch_altinkaynak_gold_quotes(
                    max_age_minutes=_altinkaynak_max_age_minutes()
                )
                note_source_health("turkey:altinkaynak-gold", True)
            except Exception as exc:
                altinkaynak_gold_cache = {}
                note_source_health(
                    "turkey:altinkaynak-gold",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
                altinkaynak_gold_error = (
                    f"altinkaynak-gold: {type(exc).__name__}: {exc}"
                )[:240]
                print(
                    f"WARNING: Altinkaynak gold verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        return altinkaynak_gold_cache or {}

    def _bank_aggregator_max_age_minutes() -> int:
        try:
            value = int(
                os.environ.get(
                    "BANK_AGGREGATOR_MAX_AGE_MINUTES",
                    "720",
                )
            )
        except ValueError:
            value = 720
        return max(value, 1)

    def get_official_bank_verifiers(
        pair: str,
        quotes: list[Any],
    ) -> tuple[
        dict[str, Mapping[str, tuple[Decimal, Decimal]]],
        dict[str, tuple[str, ...]],
    ]:
        if pair not in official_bank_cache:
            values: dict[str, tuple[Decimal, Decimal]] = {}
            errors: dict[str, str] = {}

            isbank = next(
                (quote for quote in quotes if quote.name == "İş Bankası"),
                None,
            )
            if isbank is not None:
                try:
                    values["İş Bankası"] = fetch_isbank_quote(pair)
                    note_source_health(
                        f"turkey:isbank-official:{pair}",
                        True,
                    )
                except Exception as exc:
                    note_source_health(
                        f"turkey:isbank-official:{pair}",
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                    errors["İş Bankası"] = (
                        f"isbank-official: {type(exc).__name__}: {exc}"
                    )[:240]
                    print(
                        f"WARNING: Isbank official verifier unavailable: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

            garanti = next(
                (quote for quote in quotes if quote.name == "Garanti BBVA"),
                None,
            )
            if garanti is not None:
                try:
                    values["Garanti BBVA"] = fetch_garanti_quote(pair)
                    note_source_health(
                        f"turkey:garanti-official:{pair}",
                        True,
                    )
                except Exception as exc:
                    note_source_health(
                        f"turkey:garanti-official:{pair}",
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                    errors["Garanti BBVA"] = (
                        f"garanti-official: {type(exc).__name__}: {exc}"
                    )[:240]
                    print(
                        f"WARNING: Garanti official verifier unavailable: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

                try:
                    external_quote = fetch_canlidoviz_garanti_quote(
                        pair,
                        max_age_minutes=_bank_aggregator_max_age_minutes(),
                    )
                    values["Garanti BBVA (external)"] = external_quote
                    note_source_health(
                        f"turkey:garanti-external:{pair}",
                        True,
                    )
                except Exception as exc:
                    note_source_health(
                        f"turkey:garanti-external:{pair}",
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                    existing = errors.get("Garanti BBVA", "")
                    external_error = (
                        f"garanti-external: {type(exc).__name__}: {exc}"
                    )[:240]
                    errors["Garanti BBVA"] = (
                        f"{existing}; {external_error}"
                        if existing
                        else external_error
                    )[:400]
                    print(
                        f"WARNING: Garanti external verifier unavailable: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

            kuveyt = next(
                (quote for quote in quotes if quote.name == "Kuveyt Türk"),
                None,
            )
            if kuveyt is not None:
                try:
                    values["Kuveyt Türk"] = fetch_kuveyt_quote(pair)
                    note_source_health(
                        f"turkey:kuveyt-official:{pair}",
                        True,
                    )
                except Exception as exc:
                    note_source_health(
                        f"turkey:kuveyt-official:{pair}",
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                    errors["Kuveyt Türk"] = (
                        f"kuveyt-official: {type(exc).__name__}: {exc}"
                    )[:240]
                    print(
                        f"WARNING: Kuveyt official verifier unavailable: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

            ziraat = next(
                (quote for quote in quotes if quote.name == "Ziraat Bankası"),
                None,
            )
            if ziraat is not None:
                try:
                    values["Ziraat Bankası"] = fetch_ziraat_quote(
                        pair,
                        primary_buy=Decimal(str(ziraat.buy)),
                        primary_sell=Decimal(str(ziraat.sell)),
                    )
                    note_source_health(
                        f"turkey:ziraat-official:{pair}",
                        True,
                    )
                except Exception as exc:
                    note_source_health(
                        f"turkey:ziraat-official:{pair}",
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                    errors["Ziraat Bankası"] = (
                        f"ziraat-official: {type(exc).__name__}: {exc}"
                    )[:240]
                    print(
                        f"WARNING: Ziraat official verifier unavailable: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

            official_bank_cache[pair] = values
            official_bank_errors[pair] = errors

        source_map: dict[
            str, Mapping[str, tuple[Decimal, Decimal]]
        ] = {}
        values = official_bank_cache[pair]
        if "Garanti BBVA" in values:
            source_map["garanti-official"] = {
                "Garanti BBVA": values["Garanti BBVA"],
            }
        if "Garanti BBVA (external)" in values:
            source_map["garanti-external"] = {
                "Garanti BBVA": values["Garanti BBVA (external)"],
            }
        if "İş Bankası" in values:
            source_map["isbank-official"] = {
                "İş Bankası": values["İş Bankası"],
            }
        if "Kuveyt Türk" in values:
            source_map["kuveyt-official"] = {
                "Kuveyt Türk": values["Kuveyt Türk"],
            }
        if "Ziraat Bankası" in values:
            source_map["ziraat-official"] = {
                "Ziraat Bankası": values["Ziraat Bankası"],
            }

        unavailable = {
            name: (error,)
            for name, error in official_bank_errors[pair].items()
        }
        return source_map, unavailable

    def current_history_snapshot():
        # AlanChande history intentionally depends only on neutral market feeds.
        return build_snapshot(get_usd_quotes(), get_eur_quotes())

    def build_safe_daily_digest() -> tuple[str, PostSafetyAssessment]:
        nonlocal daily_digest_cache
        nonlocal daily_digest_publish_cache

        if daily_digest_cache is None:
            daily_digest_cache = collect_digest(history_db)
            daily_digest_publish_cache = dict(daily_digest_cache.published_values)
            for source_key, error in daily_digest_cache.source_health.items():
                note_source_health(
                    source_key,
                    error is None,
                    error or "",
                )

        return daily_digest_cache.text, daily_digest_cache.assessment

    def add_alanchande(
        text: str,
        post_key: str | None = None,
        safety: PostSafetyAssessment | None = None,
    ) -> None:
        jobs.append(
            (
                "ALANCHANDE_TELEGRAM_BOT_TOKEN",
                "ALANCHANDE_CHANNEL_ID",
                text,
                post_key,
                safety,
            )
        )

    def add_kiani(text: str) -> None:
        jobs.append(
            ("KIANI_TELEGRAM_BOT_TOKEN", "KIANI_CHANNEL_ID", text, None, None)
        )

    history_db = _history_db_path()
    safety_mode = normalize_mode(os.environ.get("MARKET_SAFETY_MODE", "shadow"))

    if args.record_history:
        snapshot = current_history_snapshot()
        row_id = record_snapshot(history_db, snapshot)
        print(
            f"recorded history snapshot #{row_id} -> {history_db} "
            f"({snapshot.local_date} {snapshot.local_time[:5]} Istanbul)"
        )
        print(history_status(history_db, snapshot.local_date))
        return 0

    if args.history_status:
        local_date = datetime.now(ISTANBUL_TZ).strftime("%Y-%m-%d")
        print(history_status(history_db, local_date))
        print(f"database: {history_db}")
        return 0

    if args.safety_status:
        print(recent_safety_status(history_db))
        print()
        print(recent_source_health_status(history_db))
        print(f"database: {history_db}")
        return 0

    def build_safe_bank(pair: str) -> tuple[str, PostSafetyAssessment]:
        quotes = get_usd_quotes() if pair == "USD/TRY" else get_eur_quotes()
        previous = load_bank_fx_near_24h(history_db, pair)
        text = (
            build_usd_comparison_post(quotes, previous)
            if pair == "USD/TRY"
            else build_eur_comparison_post(quotes, previous)
        )
        altinkaynak = get_altinkaynak_currency_safe()
        extra: dict[
            str, Mapping[str, tuple[Decimal, Decimal]]
        ] = {}
        if pair in altinkaynak:
            # Altinkaynak is a market-level verifier. It can independently
            # verify the Kapalicarsi row but must not be treated as proof of a
            # specific bank's own customer quote.
            extra["altinkaynak"] = {
                "Kapalıçarşı": altinkaynak[pair],
            }

        official_sources, unavailable_by_name = get_official_bank_verifiers(
            pair,
            quotes,
        )
        extra.update(official_sources)

        assessment = assess_post(
            history_db,
            "bank-usd" if pair == "USD/TRY" else "bank-eur",
            bank_fx_observations(
                pair,
                quotes,
                extra,
                (altinkaynak_currency_error,)
                if altinkaynak_currency_error
                else (),
                unavailable_by_name,
            ),
        )
        return text, assessment

    def build_safe_fx_pulse() -> tuple[str, PostSafetyAssessment]:
        usd = get_usd_quotes()
        eur = get_eur_quotes()
        text = build_turkey_fx_pulse_post(
            usd,
            eur,
            load_bank_fx_near_24h(history_db, "USD/TRY"),
            load_bank_fx_near_24h(history_db, "EUR/TRY"),
        )
        altinkaynak_quotes = get_altinkaynak_currency_safe()
        altinkaynak_midpoints = {
            pair: (buy + sell) / Decimal("2")
            for pair, (buy, sell) in altinkaynak_quotes.items()
        }
        extra = (
            {"altinkaynak": altinkaynak_midpoints}
            if altinkaynak_midpoints
            else {}
        )
        assessment = assess_post(
            history_db,
            "fx-pulse",
            fx_pulse_observations(
                usd,
                eur,
                extra,
                (altinkaynak_currency_error,)
                if altinkaynak_currency_error
                else (),
            ),
        )
        return text, assessment

    def build_safe_iran_fx() -> tuple[str, PostSafetyAssessment]:
        nonlocal iran_fx_publish_cache

        rates = get_iran_fx()
        external = get_iran_fx_external_safe()
        adonis_try = get_iran_fx_adonis_try_safe()

        observations = []
        for code, value in rates.items():
            source_values: dict[str, Decimal] = {"tgju": value}
            unavailable: list[str] = []

            if code in external:
                source_values["pashizi"] = external[code]
            elif iran_fx_external_error:
                unavailable.append(iran_fx_external_error)

            if code == "TRY":
                if adonis_try is not None:
                    source_values["adonis"] = adonis_try
                elif iran_fx_adonis_error:
                    unavailable.append(iran_fx_adonis_error)

            observations.append(
                SafetyObservation(
                    market_key=f"iran-fx:{code}/TOMAN",
                    source_values=source_values,
                    min_sources=2,
                    max_source_deviation_pct=Decimal("2.00"),
                    suspicious_move_pct=Decimal("6.00"),
                    strong_quorum=3,
                    unavailable_sources=tuple(unavailable),
                )
            )

        assessment = assess_post(
            history_db,
            "iran-fx",
            observations,
        )

        # Publish the verified consensus reference rather than blindly using
        # the TGJU display value. This matters when two independent sources
        # agree and one provider is rejected as an outlier.
        check_by_code = {
            check.market_key.split(":", 1)[1].split("/", 1)[0]: check
            for check in assessment.checks
            if check.market_key.startswith("iran-fx:")
        }
        publish_rates: dict[str, Decimal] = {}
        for code, raw_value in rates.items():
            check = check_by_code.get(code)
            if (
                check is not None
                and check.decision == VERIFIED
                and check.reference_value is not None
            ):
                publish_rates[code] = check.reference_value
            else:
                publish_rates[code] = raw_value

        iran_fx_publish_cache = publish_rates

        previous_24h = load_published_values_near_age(
            history_db,
            "iran-fx",
            target_hours=24,
            min_age_hours=18,
            max_age_hours=30,
        )
        previous_1m = load_published_values_near_age(
            history_db,
            "iran-fx",
            target_hours=24 * 30,
            min_age_hours=24 * 25,
            max_age_hours=24 * 35,
        )
        text = build_iran_fx_post(
            publish_rates,
            percentage_changes(publish_rates, previous_24h),
            percentage_changes(publish_rates, previous_1m),
        )
        return text, assessment

    def build_safe_turkey_gold() -> tuple[str, PostSafetyAssessment]:
        quotes = get_turkey_gold()
        text = build_turkish_gold_post(
            quotes,
            load_turkey_gold_near_24h(history_db),
        )
        altinkaynak = get_altinkaynak_gold_safe()
        extra = {"altinkaynak": altinkaynak} if altinkaynak else {}
        assessment = assess_post(
            history_db,
            "turkey-gold",
            turkey_gold_observations(
                quotes,
                extra,
                (altinkaynak_gold_error,)
                if altinkaynak_gold_error
                else (),
            ),
        )
        return text, assessment

    def build_safe_iran_gold() -> tuple[str, PostSafetyAssessment]:
        market = get_iran_gold()
        text = build_iran_gold_post(
            market,
            load_iran_gold_near_24h(history_db),
        )
        external = get_iran_gold_external_safe()
        extra_sources = (
            {"dolarchand": external}
            if external
            else {}
        )
        assessment = assess_post(
            history_db,
            "iran-gold",
            iran_gold_observations(
                market,
                extra_sources=extra_sources,
                unavailable_sources=(
                    (iran_gold_external_error,)
                    if iran_gold_external_error
                    else ()
                ),
            ),
        )
        return text, assessment

    def build_safe_usdt() -> tuple[str, PostSafetyAssessment]:
        quotes = get_hybrid_usdt()
        current_buy = {quote.exchange: quote.buy_toman for quote in quotes}
        previous_24h = load_published_values_near_age(
            history_db,
            "usdt-buy",
            target_hours=24,
            min_age_hours=18,
            max_age_hours=30,
        )
        previous_1m = load_published_values_near_age(
            history_db,
            "usdt-buy",
            target_hours=24 * 30,
            min_age_hours=24 * 25,
            max_age_hours=24 * 35,
        )
        text = build_hybrid_usdt_post(
            quotes,
            percentage_changes(current_buy, previous_24h),
            percentage_changes(current_buy, previous_1m),
        )
        assessment = assess_post(
            history_db,
            "usdt",
            usdt_observations(quotes),
        )
        return text, assessment

    if args.post in {"bank-comparison", "bank-comparisons", "all"}:
        text, safety = build_safe_bank("USD/TRY")
        add_alanchande(text, "bank-usd", safety)

    if args.post in {"eur-bank-comparison", "bank-comparisons"}:
        text, safety = build_safe_bank("EUR/TRY")
        add_alanchande(text, "bank-eur", safety)

    if args.post in {"alanchande-converter", "demo-formats"}:
        add_alanchande(build_alanchande_converter_post(get_rates()))

    if args.post in {"alanchande-snapshot", "demo-formats"}:
        add_alanchande(build_alanchande_snapshot_post(get_rates(), get_usd_quotes()))

    if args.post == "alanchande-daily-change":
        current = current_history_snapshot()
        stored = load_day(history_db, current.local_date)
        add_alanchande(build_alanchande_daily_change_post(stored, current))

    if args.post == "alanchande-fx-pulse":
        text, safety = build_safe_fx_pulse()
        add_alanchande(text, "fx-pulse", safety)

    if args.post == "alanchande-daily-digest":
        text, safety = build_safe_daily_digest()
        add_alanchande(text, "daily-digest", safety)

    if args.post == "alanchande-iran-fx":
        text, safety = build_safe_iran_fx()
        add_alanchande(text, "iran-fx", safety)

    if args.post == "alanchande-turkey-gold":
        text, safety = build_safe_turkey_gold()
        add_alanchande(text, "turkey-gold", safety)

    if args.post == "alanchande-iran-gold":
        text, safety = build_safe_iran_gold()
        add_alanchande(text, "iran-gold", safety)

    if args.post == "alanchande-usdt-exchanges":
        text, safety = build_safe_usdt()
        add_alanchande(text, "usdt", safety)

    if args.post == "alanchande-markets":
        safe_builders = [
            ("turkey-gold", build_safe_turkey_gold),
            ("iran-gold", build_safe_iran_gold),
            ("usdt", build_safe_usdt),
        ]
        built_count = 0
        for key, builder in safe_builders:
            try:
                text, safety = builder()
            except Exception as exc:
                print(
                    f"WARNING: skipped {key}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            add_alanchande(text, key, safety)
            built_count += 1

        if built_count == 0:
            raise RuntimeError("All AlanChande market posts failed")

    if args.post == "alanchande-daily":
        safe_builders = [
            ("bank-usd", lambda: build_safe_bank("USD/TRY")),
            ("iran-fx", build_safe_iran_fx),
            ("fx-pulse", build_safe_fx_pulse),
            ("turkey-gold", build_safe_turkey_gold),
            ("iran-gold", build_safe_iran_gold),
            ("usdt", build_safe_usdt),
        ]
        built_count = 0
        for key, builder in safe_builders:
            try:
                text, safety = builder()
            except Exception as exc:
                print(
                    f"WARNING: skipped daily {key}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            add_alanchande(text, key, safety)
            built_count += 1

        if built_count == 0:
            raise RuntimeError("All AlanChande daily posts failed")

    if args.post == "alanchande-usdt-tgju":
        add_alanchande(build_usdt_exchange_post(get_iran_usdt()))

    if args.post == "alanchande-usdt-seven":
        text, safety = build_safe_usdt()
        add_alanchande(text, "usdt", safety)

    if args.post == "alanchande-usdt-nobitex":
        add_alanchande(build_nobitex_usdt_post(get_nobitex_usdt()))

    if args.post == "alanchande-usdt-wallex":
        add_alanchande(build_wallex_usdt_post(get_wallex_usdt()))

    if args.post == "alanchande-usdt-tabdeal":
        add_alanchande(build_tabdeal_usdt_post(get_tabdeal_usdt()))

    if args.post == "alanchande-usdt-exir":
        add_alanchande(build_exir_usdt_post(get_exir_usdt()))

    if args.post == "alanchande-usdt-bitpin":
        add_alanchande(build_bitpin_usdt_post(get_bitpin_usdt()))

    if args.post == "alanchande-usdt-ramzinex":
        add_alanchande(build_ramzinex_usdt_post(get_ramzinex_usdt()))

    if args.post == "alanchande-usdt-abantether":
        add_alanchande(build_abantether_usdt_post(get_abantether_usdt()))

    if args.post == "alanchande-usdt-tetherland":
        add_alanchande(build_tetherland_usdt_post(get_tetherland_usdt()))

    if args.post == "alanchande-usdt-direct":
        add_alanchande(fetch_and_build_direct_usdt_comparison())

    if args.post in {"kiani-rates", "all"}:
        add_kiani(build_kiani_rate_post(get_rates()))

    if args.post in {"kiani-try", "demo-formats"}:
        add_kiani(
            build_kiani_try_post(
                get_rates(),
                telegram_url=os.environ.get(
                    "KIANI_CONTACT_TELEGRAM",
                    "https://t.me/TL905411603664",
                ).strip()
                or "https://t.me/TL905411603664",
                whatsapp_url=os.environ.get(
                    "KIANI_CONTACT_WHATSAPP",
                    "https://wa.me/905392905686",
                ).strip()
                or "https://wa.me/905392905686",
            )
        )

    if args.post in {"kiani-examples", "demo-formats"}:
        add_kiani(build_kiani_try_receive_post(get_rates()))

    if args.post in {"kiani-examples-reverse", "demo-formats"}:
        add_kiani(build_kiani_toman_receive_post(get_rates()))

    if args.dry_run:
        print(f"MARKET_SAFETY_MODE={safety_mode}")
        for event in source_health_events.values():
            state = "HEALTHY" if event.healthy else "DEGRADED"
            detail = f" | {event.detail}" if event.detail else ""
            print(f"SOURCE HEALTH {event.source_key}: {state}{detail}")
        for token_env, destination_env, text, post_key, safety in jobs:
            if safety is not None:
                print(
                    f"SAFETY {safety.post_type}: {safety.decision} | "
                    f"{safety.reason}"
                )
            print(
                f"\n===== {destination_env} (bot: {token_env}) =====\n{text}\n"
            )
        return 0

    admin_chat_id = os.environ.get("ALANCHANDE_ADMIN_CHAT_ID", "").strip() or None
    admin_token = (
        os.environ.get("ALANCHANDE_ADMIN_BOT_TOKEN", "").strip()
        or os.environ.get("ALANCHANDE_TELEGRAM_BOT_TOKEN", "").strip()
        or None
    )
    try:
        alert_repeat_minutes = int(
            os.environ.get("MARKET_SAFETY_ALERT_REPEAT_MINUTES", "60")
        )
    except ValueError:
        alert_repeat_minutes = 60

    for event in source_health_events.values():
        record_source_health_event(history_db, event)
        try:
            action = maybe_notify_source_health(
                history_db,
                event,
                token=admin_token,
                chat_id=admin_chat_id,
                repeat_minutes=alert_repeat_minutes,
            )
            if action == "degraded":
                print(
                    f"SOURCE DEGRADED -> {event.source_key}: "
                    f"{event.detail or 'unavailable'}",
                    file=sys.stderr,
                )
            elif action == "recovery":
                print(
                    f"SOURCE RECOVERED -> {event.source_key}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(
                f"WARNING: source-health admin alert failed for "
                f"{event.source_key}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    send_failures: list[str] = []

    for token_env, destination_env, text, post_key, safety in jobs:
        if safety is not None and not publication_allowed(safety_mode, safety):
            record_assessment(
                history_db,
                safety,
                mode=safety_mode,
                published=False,
            )
            print(
                f"BLOCKED -> {destination_env}: {safety.post_type} | "
                f"{safety.reason}",
                file=sys.stderr,
            )
            try:
                maybe_notify_admin(
                    history_db,
                    safety,
                    mode=safety_mode,
                    token=admin_token,
                    chat_id=admin_chat_id,
                    repeat_minutes=alert_repeat_minutes,
                )
            except Exception as exc:
                print(
                    f"WARNING: admin safety alert failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            continue

        try:
            token = _required_env(token_env)
            chat_id = _required_env(destination_env)
            telegram_send(token, chat_id, text)
        except Exception as exc:
            failure = (
                f"{destination_env}"
                f"{f'/{post_key}' if post_key else ''}: "
                f"{type(exc).__name__}: {exc}"
            )
            send_failures.append(failure)
            print(f"SEND FAILED -> {failure}", file=sys.stderr)

            # A failed Telegram delivery must never advance the accepted
            # safety baseline or any Δ24H/Δ1M history.
            if safety is not None:
                record_assessment(
                    history_db,
                    safety,
                    mode=safety_mode,
                    published=False,
                )
            continue

        print(f"sent -> {destination_env} using {token_env}")

        if post_key is not None:
            sent_market_posts.add(post_key)
            if safety is None or safety.decision == VERIFIED:
                verified_sent_market_posts.add(post_key)

        if safety is not None:
            record_assessment(
                history_db,
                safety,
                mode=safety_mode,
                published=True,
            )
            if safety.decision != VERIFIED:
                print(
                    f"SHADOW SAFETY {safety.post_type}: {safety.decision} | "
                    f"{safety.reason}",
                    file=sys.stderr,
                )
            try:
                maybe_notify_admin(
                    history_db,
                    safety,
                    mode=safety_mode,
                    token=admin_token,
                    chat_id=admin_chat_id,
                    repeat_minutes=alert_repeat_minutes,
                )
            except Exception as exc:
                print(
                    f"WARNING: admin safety alert failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

    # Save bank-market snapshots only after successful Telegram delivery.
    # Dry runs never mutate history. On the next daily post, the snapshot
    # closest to 24 hours old is used for Δ24H.
    if (
        "bank-usd" in verified_sent_market_posts
        and "fx-pulse" not in verified_sent_market_posts
    ):
        timestamp = record_bank_fx_quotes(history_db, "USD/TRY", get_usd_quotes())
        print(f"recorded USD/TRY bank snapshot -> {timestamp}")

    if (
        "bank-eur" in verified_sent_market_posts
        and "fx-pulse" not in verified_sent_market_posts
    ):
        timestamp = record_bank_fx_quotes(history_db, "EUR/TRY", get_eur_quotes())
        print(f"recorded EUR/TRY bank snapshot -> {timestamp}")

    if "fx-pulse" in verified_sent_market_posts:
        usd_timestamp = record_bank_fx_quotes(history_db, "USD/TRY", get_usd_quotes())
        eur_timestamp = record_bank_fx_quotes(history_db, "EUR/TRY", get_eur_quotes())
        print(f"recorded USD/TRY daily FX snapshot -> {usd_timestamp}")
        print(f"recorded EUR/TRY daily FX snapshot -> {eur_timestamp}")

    if "turkey-gold" in verified_sent_market_posts:
        timestamp = record_turkey_gold_quotes(history_db, get_turkey_gold())
        print(f"recorded Turkey gold snapshot -> {timestamp}")

    if "iran-gold" in verified_sent_market_posts:
        timestamp = record_iran_gold_market(history_db, get_iran_gold())
        print(f"recorded Iran gold snapshot -> {timestamp}")

    if "usdt" in verified_sent_market_posts:
        timestamp = record_published_values(
            history_db,
            "usdt-buy",
            {quote.exchange: quote.buy_toman for quote in get_hybrid_usdt()},
        )
        print(f"recorded verified USDT snapshot -> {timestamp}")

    if "iran-fx" in verified_sent_market_posts:
        if iran_fx_publish_cache is None:
            raise RuntimeError(
                "Verified Iran FX post has no consensus publish snapshot"
            )
        timestamp = record_published_values(
            history_db,
            "iran-fx",
            iran_fx_publish_cache,
        )
        print(f"recorded verified Iran FX snapshot -> {timestamp}")

    if "daily-digest" in verified_sent_market_posts:
        if daily_digest_publish_cache is None:
            raise RuntimeError(
                "Verified daily digest has no consensus publish snapshot"
            )
        timestamp = record_published_values(
            history_db,
            "daily-digest",
            daily_digest_publish_cache,
        )
        print(f"recorded verified daily digest snapshot -> {timestamp}")

    if send_failures:
        print(
            f"{len(send_failures)} Telegram send(s) failed after all eligible "
            "jobs were attempted",
            file=sys.stderr,
        )
        for failure in send_failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
