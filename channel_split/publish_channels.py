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
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from altinkaynak_verifier import (
    fetch_altinkaynak_currency,
    fetch_altinkaynak_gold,
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
from iran_gold_history import load_iran_gold_near_24h, record_iran_gold_market
from iran_usdt import build_usdt_exchange_post, fetch_usdt_exchange_quotes
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
    collect_hybrid_usdt_quotes,
    fetch_and_build_hybrid_usdt_post,
)
from market_pulse import build_turkey_fx_pulse_post
from admin_alerts import maybe_notify_admin
from market_safety import (
    PostSafetyAssessment,
    assess_post,
    bank_fx_observations,
    fx_pulse_observations,
    iran_gold_observations,
    normalize_mode,
    publication_allowed,
    recent_safety_status,
    record_assessment,
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


def build_kiani_rate_post(rates: dict[str, Decimal]) -> str:
    return "\n".join(
        [
            "💱 <b>نرخ معامله صرافی کیانی</b>",
            "",
            f"🇹🇷 فروش لیر به شما: <b>{_fmt_int(rates['buy_lira'])}</b> تومان",
            f"🇹🇷 خرید لیر از شما: <b>{_fmt_int(rates['sell_lira'])}</b> تومان",
            "",
            f"🪙 فروش تتر به شما: <b>{_fmt_int(rates['buy_usdt'])}</b> تومان",
            f"🪙 خرید تتر از شما: <b>{_fmt_int(rates['sell_usdt'])}</b> تومان",
            "",
            f"🔄 لیر → تتر: هر ۱ تتر = <b>{_fmt_cross(rates['lira_to_usdt'])}</b> لیر",
            f"🔄 تتر → لیر: هر ۱ تتر = <b>{_fmt_cross(rates['usdt_to_lira'])}</b> لیر",
            "",
            f"🕒 بروزرسانی: {_now_text()} به وقت استانبول",
            "🤖 ثبت سفارش: @Kianiexchangebot",
            "📊 نرخ‌های بازار و محتوای تحلیلی: @alanchande_com",
        ]
    )


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


def build_kiani_try_post(rates: dict[str, Decimal]) -> str:
    return "\n".join(
        [
            "🇹🇷 <b>نرخ لیر | صرافی کیانی</b>",
            "",
            f"فروش به شما: <b>{_fmt_int(rates['buy_lira'])}</b> تومان",
            f"خرید از شما: <b>{_fmt_int(rates['sell_lira'])}</b> تومان",
            "",
            f"🕒 {_now_text()} استانبول",
            "🤖 ثبت سفارش: @Kianiexchangebot",
        ]
    )


def build_kiani_examples_post(rates: dict[str, Decimal]) -> str:
    sell_try = rates["buy_lira"]
    amounts = (Decimal("10000"), Decimal("50000"), Decimal("100000"))
    lines = [
        "🧮 <b>برای خرید لیر چقدر تومان لازم است؟</b>",
        "",
    ]
    for try_amount in amounts:
        toman = try_amount * sell_try
        lines.append(f"🇹🇷 {_fmt_int(try_amount)} لیر ≈ <b>{_fmt_int(toman)}</b> تومان")
    lines.extend(
        [
            "",
            f"بر اساس نرخ فروش فعلی: <b>{_fmt_int(sell_try)}</b> تومان",
            "🤖 ثبت سفارش: @Kianiexchangebot",
        ]
    )
    return "\n".join(lines)


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
            "kiani-rates",
            "kiani-try",
            "kiani-examples",
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
    successful_market_posts: set[str] = set()
    sent_market_posts: set[str] = set()
    rates_cache: dict[str, Decimal] | None = None
    usd_quotes_cache: list[Any] | None = None
    eur_quotes_cache: list[Any] | None = None
    turkey_gold_cache: list[Any] | None = None
    iran_gold_cache: Any | None = None
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
    altinkaynak_currency_cache: dict[str, Decimal] | None = None
    altinkaynak_currency_attempted = False
    altinkaynak_currency_error: str | None = None
    altinkaynak_gold_cache: dict[str, Decimal] | None = None
    altinkaynak_gold_attempted = False
    altinkaynak_gold_error: str | None = None

    def get_rates() -> dict[str, Decimal]:
        nonlocal rates_cache
        if rates_cache is None:
            rates_cache = fetch_kiani_rates(os.environ.get("KIANI_RATES_URL", DEFAULT_RATES_URL))
        return rates_cache

    def get_usd_quotes() -> list[Any]:
        nonlocal usd_quotes_cache
        if usd_quotes_cache is None:
            usd_quotes_cache = fetch_usd_comparison()
        return usd_quotes_cache

    def get_eur_quotes() -> list[Any]:
        nonlocal eur_quotes_cache
        if eur_quotes_cache is None:
            eur_quotes_cache = fetch_eur_comparison()
        return eur_quotes_cache

    def get_turkey_gold() -> list[Any]:
        nonlocal turkey_gold_cache
        if turkey_gold_cache is None:
            turkey_gold_cache = fetch_turkish_gold_quotes()
        return turkey_gold_cache

    def get_iran_gold() -> Any:
        nonlocal iran_gold_cache
        if iran_gold_cache is None:
            iran_gold_cache = fetch_iran_gold_market()
        return iran_gold_cache

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
            hybrid_usdt_cache = collect_hybrid_usdt_quotes()
        return hybrid_usdt_cache

    def _altinkaynak_max_age_minutes() -> int:
        try:
            value = int(os.environ.get("ALTINKAYNAK_MAX_AGE_MINUTES", "90"))
        except ValueError:
            value = 90
        return max(value, 1)

    def get_altinkaynak_currency_safe() -> dict[str, Decimal]:
        nonlocal altinkaynak_currency_cache
        nonlocal altinkaynak_currency_attempted
        nonlocal altinkaynak_currency_error
        if not altinkaynak_currency_attempted:
            altinkaynak_currency_attempted = True
            try:
                altinkaynak_currency_cache = fetch_altinkaynak_currency(
                    max_age_minutes=_altinkaynak_max_age_minutes()
                )
            except Exception as exc:
                altinkaynak_currency_cache = {}
                altinkaynak_currency_error = (
                    f"altinkaynak-currency: {type(exc).__name__}: {exc}"
                )[:240]
                print(
                    f"WARNING: Altinkaynak currency verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        return altinkaynak_currency_cache or {}

    def get_altinkaynak_gold_safe() -> dict[str, Decimal]:
        nonlocal altinkaynak_gold_cache
        nonlocal altinkaynak_gold_attempted
        nonlocal altinkaynak_gold_error
        if not altinkaynak_gold_attempted:
            altinkaynak_gold_attempted = True
            try:
                altinkaynak_gold_cache = fetch_altinkaynak_gold(
                    max_age_minutes=_altinkaynak_max_age_minutes()
                )
            except Exception as exc:
                altinkaynak_gold_cache = {}
                altinkaynak_gold_error = (
                    f"altinkaynak-gold: {type(exc).__name__}: {exc}"
                )[:240]
                print(
                    f"WARNING: Altinkaynak gold verifier unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        return altinkaynak_gold_cache or {}

    def current_history_snapshot():
        # AlanChande history intentionally depends only on neutral market feeds.
        return build_snapshot(get_usd_quotes(), get_eur_quotes())

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
        extra = {}
        if pair in altinkaynak:
            # Altinkaynak is a market-level verifier. It can independently
            # verify the Kapalicarsi row but must not be treated as proof of a
            # specific bank's own customer quote.
            extra = {
                "altinkaynak": {
                    "Kapalıçarşı": altinkaynak[pair],
                }
            }
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
        altinkaynak = get_altinkaynak_currency_safe()
        extra = {"altinkaynak": altinkaynak} if altinkaynak else {}
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
        assessment = assess_post(
            history_db,
            "iran-gold",
            iran_gold_observations(market),
        )
        return text, assessment

    def build_safe_usdt() -> tuple[str, PostSafetyAssessment]:
        quotes = get_hybrid_usdt()
        text = build_hybrid_usdt_post(quotes)
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

    if args.post == "alanchande-turkey-gold":
        text, safety = build_safe_turkey_gold()
        add_alanchande(text, "turkey-gold", safety)
        successful_market_posts.add("turkey-gold")

    if args.post == "alanchande-iran-gold":
        text, safety = build_safe_iran_gold()
        add_alanchande(text, "iran-gold", safety)
        successful_market_posts.add("iran-gold")

    if args.post == "alanchande-usdt-exchanges":
        text, safety = build_safe_usdt()
        add_alanchande(text, "usdt", safety)
        successful_market_posts.add("usdt")

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
            successful_market_posts.add(key)
            built_count += 1

        if built_count == 0:
            raise RuntimeError("All AlanChande market posts failed")

    if args.post == "alanchande-daily":
        safe_builders = [
            ("bank-usd", lambda: build_safe_bank("USD/TRY")),
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
            successful_market_posts.add(key)
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
        add_kiani(build_kiani_try_post(get_rates()))

    if args.post in {"kiani-examples", "demo-formats"}:
        add_kiani(build_kiani_examples_post(get_rates()))

    if args.dry_run:
        print(f"MARKET_SAFETY_MODE={safety_mode}")
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

        token = _required_env(token_env)
        chat_id = _required_env(destination_env)
        telegram_send(token, chat_id, text)
        print(f"sent -> {destination_env} using {token_env}")

        if post_key is not None:
            sent_market_posts.add(post_key)

        if safety is not None:
            record_assessment(
                history_db,
                safety,
                mode=safety_mode,
                published=True,
            )
            if safety.decision != "VERIFIED":
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
    if "bank-usd" in sent_market_posts and "fx-pulse" not in sent_market_posts:
        timestamp = record_bank_fx_quotes(history_db, "USD/TRY", get_usd_quotes())
        print(f"recorded USD/TRY bank snapshot -> {timestamp}")

    if "bank-eur" in sent_market_posts and "fx-pulse" not in sent_market_posts:
        timestamp = record_bank_fx_quotes(history_db, "EUR/TRY", get_eur_quotes())
        print(f"recorded EUR/TRY bank snapshot -> {timestamp}")

    if "fx-pulse" in sent_market_posts:
        usd_timestamp = record_bank_fx_quotes(history_db, "USD/TRY", get_usd_quotes())
        eur_timestamp = record_bank_fx_quotes(history_db, "EUR/TRY", get_eur_quotes())
        print(f"recorded USD/TRY daily FX snapshot -> {usd_timestamp}")
        print(f"recorded EUR/TRY daily FX snapshot -> {eur_timestamp}")

    if "turkey-gold" in sent_market_posts:
        timestamp = record_turkey_gold_quotes(history_db, get_turkey_gold())
        print(f"recorded Turkey gold snapshot -> {timestamp}")

    if "iran-gold" in sent_market_posts:
        timestamp = record_iran_gold_market(history_db, get_iran_gold())
        print(f"recorded Iran gold snapshot -> {timestamp}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
