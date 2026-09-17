#!/usr/bin/env python3
"""Publish AlanChande information posts and Kiani transaction posts.

The channel IDs are always environment variables. That lets us test against two
throw-away channels first, then move to the real channels by changing only the
environment configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bank_compare import build_usd_comparison_post, fetch_usd_comparison

DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"


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


def fetch_kiani_rates(url: str = DEFAULT_RATES_URL, timeout: int = 20) -> dict[str, Decimal]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "Kiani-TelegramPublisher/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Kiani rates API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load Kiani rates: {exc}") from exc

    raw = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("Kiani rates API response has no rates object")

    keys = ("buy_lira", "sell_lira", "buy_usdt", "sell_usdt", "lira_to_usdt", "usdt_to_lira")
    missing = [key for key in keys if key not in raw]
    if missing:
        raise ValueError("Missing Kiani rates: " + ", ".join(missing))
    return {key: _positive_decimal(raw[key], key) for key in keys}


def _fmt_int(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _fmt_cross(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}".rstrip("0").rstrip(".")


def build_kiani_rate_post(rates: dict[str, Decimal]) -> str:
    return "\n".join(
        [
            "💱 <b>نرخ معامله صرافی کیانی</b>",
            "",
            f"🇹🇷 فروش لیر به شما: <b>{_fmt_int(rates['buy_lira'])}</b>",
            f"🇹🇷 خرید لیر از شما: <b>{_fmt_int(rates['sell_lira'])}</b>",
            "",
            f"🪙 فروش تتر به شما: <b>{_fmt_int(rates['buy_usdt'])}</b>",
            f"🪙 خرید تتر از شما: <b>{_fmt_int(rates['sell_usdt'])}</b>",
            f"💲 لیر → تتر: {_fmt_cross(rates['lira_to_usdt'])}",
            f"💲 تتر → لیر: {_fmt_cross(rates['usdt_to_lira'])}",
            "",
            "🤖 ثبت سفارش: @Kianiexchangebot",
            "📊 نرخ‌های بازار و محتوای تحلیلی: @alanchande_com",
        ]
    )


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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--post",
        choices=("bank-comparison", "kiani-rates", "all"),
        default="all",
        help="Which split-channel post to build/send",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print posts instead of sending to Telegram")
    args = parser.parse_args()

    jobs: list[tuple[str, str]] = []

    if args.post in {"bank-comparison", "all"}:
        quotes = fetch_usd_comparison()
        jobs.append(("ALANCHANDE_CHANNEL_ID", build_usd_comparison_post(quotes)))

    if args.post in {"kiani-rates", "all"}:
        rates = fetch_kiani_rates(os.environ.get("KIANI_RATES_URL", DEFAULT_RATES_URL))
        jobs.append(("KIANI_CHANNEL_ID", build_kiani_rate_post(rates)))

    if args.dry_run:
        for destination_env, text in jobs:
            print(f"\n===== {destination_env} =====\n{text}\n")
        return 0

    token = _required_env("TELEGRAM_BOT_TOKEN")
    for destination_env, text in jobs:
        chat_id = _required_env(destination_env)
        telegram_send(token, chat_id, text)
        print(f"sent {args.post} -> {destination_env}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
