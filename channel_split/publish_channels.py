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
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bank_compare import (
    build_eur_comparison_post,
    build_usd_comparison_post,
    fetch_eur_comparison,
    fetch_usd_comparison,
)
from gold_prices import build_turkish_gold_post, fetch_turkish_gold_quotes
from iran_gold import build_iran_gold_post, fetch_iran_gold_market
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
from primary_usdt import build_primary_usdt_post
from hybrid_usdt_compare import fetch_and_build_hybrid_usdt_post
from market_history import (
    DEFAULT_HISTORY_DB,
    build_alanchande_daily_change_post,
    build_snapshot,
    history_status,
    load_day,
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
    parser.add_argument("--dry-run", action="store_true", help="Print posts instead of sending to Telegram")
    args = parser.parse_args()

    # (token_env, destination_env, text)
    jobs: list[tuple[str, str, str]] = []
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

    def current_history_snapshot():
        # AlanChande history intentionally depends only on neutral market feeds.
        return build_snapshot(get_usd_quotes(), get_eur_quotes())

    def add_alanchande(text: str) -> None:
        jobs.append(("ALANCHANDE_TELEGRAM_BOT_TOKEN", "ALANCHANDE_CHANNEL_ID", text))

    def add_kiani(text: str) -> None:
        jobs.append(("KIANI_TELEGRAM_BOT_TOKEN", "KIANI_CHANNEL_ID", text))

    history_db = _history_db_path()

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

    if args.post in {"bank-comparison", "bank-comparisons", "all"}:
        add_alanchande(build_usd_comparison_post(get_usd_quotes()))

    if args.post in {"eur-bank-comparison", "bank-comparisons"}:
        add_alanchande(build_eur_comparison_post(get_eur_quotes()))

    if args.post in {"alanchande-converter", "demo-formats"}:
        add_alanchande(build_alanchande_converter_post(get_rates()))

    if args.post in {"alanchande-snapshot", "demo-formats"}:
        add_alanchande(build_alanchande_snapshot_post(get_rates(), get_usd_quotes()))

    if args.post == "alanchande-daily-change":
        current = current_history_snapshot()
        stored = load_day(history_db, current.local_date)
        add_alanchande(build_alanchande_daily_change_post(stored, current))

    if args.post in {"alanchande-turkey-gold", "alanchande-markets"}:
        add_alanchande(build_turkish_gold_post(get_turkey_gold()))

    if args.post in {"alanchande-iran-gold", "alanchande-markets"}:
        add_alanchande(build_iran_gold_post(get_iran_gold()))

    if args.post in {"alanchande-usdt-exchanges", "alanchande-markets"}:
        add_alanchande(build_primary_usdt_post())

    if args.post == "alanchande-usdt-tgju":
        add_alanchande(build_usdt_exchange_post(get_iran_usdt()))

    if args.post == "alanchande-usdt-seven":
        add_alanchande(fetch_and_build_hybrid_usdt_post())

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
        for token_env, destination_env, text in jobs:
            print(f"\n===== {destination_env} (bot: {token_env}) =====\n{text}\n")
        return 0

    for token_env, destination_env, text in jobs:
        token = _required_env(token_env)
        chat_id = _required_env(destination_env)
        telegram_send(token, chat_id, text)
        print(f"sent -> {destination_env} using {token_env}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
