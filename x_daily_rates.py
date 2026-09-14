#!/usr/bin/env python3
"""Publish Kiani Exchange customer rates to X.

The production mini-app remains the source of truth. This script reads the same
public `/api/rates/current` payload that powers the mini-app and supports:

- regular rate posts (with or without links),
- time-of-day variants so scheduled posts are not identical,
- significant-rate-change alerts compared with the last published rates.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"
X_CREATE_POST_URL = "https://api.x.com/2/tweets"
WHATSAPP_URL = "https://wa.me/905411603664"
MINIAPP_URL = "https://miniapp.kiani.exchange"
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

REQUIRED_RATE_KEYS = (
    "buy_lira",
    "sell_lira",
    "buy_usdt",
    "sell_usdt",
    "lira_to_usdt",
    "usdt_to_lira",
)
ALERT_RATE_KEYS = (
    "buy_lira",
    "sell_lira",
    "buy_usdt",
    "sell_usdt",
)
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}

POST_TITLES = {
    "standard": "صرافی کیانی",
    "morning": "☀️ نرخ صبح صرافی کیانی",
    "afternoon": "📊 بروزرسانی نرخ صرافی کیانی",
    "evening": "🌙 نرخ عصر صرافی کیانی",
}

ALERT_LABELS = {
    "buy_lira": ("🇹🇷", "فروش لیر"),
    "sell_lira": ("🇹🇷", "خرید لیر"),
    "buy_usdt": ("🪙", "فروش تتر"),
    "sell_usdt": ("🪙", "خرید تتر"),
}


def _positive_decimal(value: Any, key: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Rate {key!r} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Rate {key!r} must be a positive finite number")
    return parsed


def fetch_current_rates(
    url: str = DEFAULT_RATES_URL,
    timeout: int = 20,
    attempts: int = 5,
    retry_delay: int = 15,
) -> dict[str, Decimal]:
    """Fetch current rates, retrying temporary upstream/server failures."""
    attempts = max(1, attempts)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "KianiExchange-XPublisher/1.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)

            raw_rates = payload.get("rates") if isinstance(payload, dict) else None
            if not isinstance(raw_rates, dict):
                raise ValueError("Rates API response does not contain a 'rates' object")

            missing = [key for key in REQUIRED_RATE_KEYS if key not in raw_rates]
            if missing:
                raise ValueError(f"Rates API response is missing: {', '.join(missing)}")

            return {key: _positive_decimal(raw_rates[key], key) for key in REQUIRED_RATE_KEYS}

        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            last_error = RuntimeError(f"Rates API returned HTTP {exc.code}: {detail}")
            retryable = exc.code in TRANSIENT_HTTP_CODES
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = RuntimeError(f"Could not load Kiani rates: {exc}")
            retryable = True
        except ValueError:
            raise

        if not retryable or attempt == attempts:
            assert last_error is not None
            raise last_error

        print(
            f"Rates fetch attempt {attempt}/{attempts} failed; retrying in {retry_delay}s...",
            file=sys.stderr,
        )
        time.sleep(retry_delay)

    assert last_error is not None
    raise last_error


def _format_integer_rate(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def _format_cross_rate(value: Decimal) -> str:
    rendered = f"{value.quantize(Decimal('0.01')):.2f}"
    return rendered.rstrip("0").rstrip(".")


def _format_rate_for_key(key: str, value: Decimal) -> str:
    if key in {"buy_lira", "sell_lira", "buy_usdt", "sell_usdt"}:
        return _format_integer_rate(value)
    return _format_cross_rate(value)


def build_post_text(
    rates: dict[str, Decimal],
    include_link: bool = True,
    include_whatsapp: bool = True,
    variant: str = "standard",
) -> str:
    title = POST_TITLES.get(variant, POST_TITLES["standard"])
    lines = [
        title,
        "",
        f"🇹🇷 فروش لیر به شما: {_format_integer_rate(rates['buy_lira'])}",
        f"🇹🇷 خرید لیر از شما: {_format_integer_rate(rates['sell_lira'])}",
        f"🪙 فروش تتر به شما: {_format_integer_rate(rates['buy_usdt'])}",
        f"🪙 خرید تتر از شما: {_format_integer_rate(rates['sell_usdt'])}",
        f"💲 لیر به تتر: {_format_cross_rate(rates['lira_to_usdt'])}",
        f"💲 تتر به لیر: {_format_cross_rate(rates['usdt_to_lira'])}",
    ]

    if include_whatsapp:
        lines.extend(["", "معامله روی خط واتسپ و تلگرام", "", WHATSAPP_URL])
    if include_link:
        lines.extend(["", MINIAPP_URL])

    return "\n".join(lines)


def calculate_significant_changes(
    previous: dict[str, Decimal],
    current: dict[str, Decimal],
    threshold_percent: Decimal = Decimal("0.5"),
) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    """Return alert-worthy changes, sorted by absolute percentage movement."""
    changes: list[tuple[str, Decimal, Decimal, Decimal]] = []
    threshold = abs(threshold_percent)

    for key in ALERT_RATE_KEYS:
        old = previous.get(key)
        new = current.get(key)
        if old is None or new is None or old <= 0:
            continue
        percent = ((new - old) / old) * Decimal("100")
        if abs(percent) >= threshold:
            changes.append((key, old, new, percent))

    changes.sort(key=lambda item: abs(item[3]), reverse=True)
    return changes


def build_alert_text(
    changes: list[tuple[str, Decimal, Decimal, Decimal]],
    now: datetime | None = None,
) -> str:
    """Build a link-free rate movement alert."""
    if not changes:
        raise ValueError("Cannot build an alert without significant changes")

    timestamp = (now or datetime.now(ISTANBUL_TZ)).astimezone(ISTANBUL_TZ)
    lines = ["🚨 تغییر قابل توجه نرخ", ""]

    for key, old, new, percent in changes[:4]:
        emoji, label = ALERT_LABELS[key]
        lines.append(
            f"{emoji} {label}: {_format_rate_for_key(key, old)} → "
            f"{_format_rate_for_key(key, new)} ({percent:+.2f}٪)"
        )

    lines.extend(
        [
            "",
            "نسبت به آخرین نرخ منتشرشده",
            f"🕒 بروزرسانی: {timestamp:%H:%M}",
        ]
    )
    return "\n".join(lines)


def load_rate_state(path: str) -> dict[str, Decimal] | None:
    state_path = Path(path)
    if not state_path.exists():
        return None

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        raw_rates = payload.get("rates") if isinstance(payload, dict) else None
        if not isinstance(raw_rates, dict):
            return None
        return {
            key: _positive_decimal(raw_rates[key], key)
            for key in REQUIRED_RATE_KEYS
            if key in raw_rates
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_rate_state(path: str, rates: dict[str, Decimal]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(ISTANBUL_TZ).isoformat(),
        "rates": {key: str(rates[key]) for key in REQUIRED_RATE_KEYS},
    }
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _oauth_encode(value: str) -> str:
    return quote(value, safe="~-._")


def _oauth1_authorization_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str:
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    normalized = "&".join(
        f"{_oauth_encode(key)}={_oauth_encode(value)}"
        for key, value in sorted(oauth_params.items())
    )
    signature_base = "&".join(
        (
            method.upper(),
            _oauth_encode(url),
            _oauth_encode(normalized),
        )
    )
    signing_key = f"{_oauth_encode(consumer_secret)}&{_oauth_encode(access_token_secret)}"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        signature_base.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("ascii")

    return "OAuth " + ", ".join(
        f'{_oauth_encode(key)}="{_oauth_encode(value)}"'
        for key, value in sorted(oauth_params.items())
    )


def publish_to_x(text: str, timeout: int = 20) -> dict[str, Any]:
    required_env = {
        "X_API_KEY": os.getenv("X_API_KEY", "").strip(),
        "X_API_SECRET": os.getenv("X_API_SECRET", "").strip(),
        "X_ACCESS_TOKEN": os.getenv("X_ACCESS_TOKEN", "").strip(),
        "X_ACCESS_TOKEN_SECRET": os.getenv("X_ACCESS_TOKEN_SECRET", "").strip(),
    }
    missing = [name for name, value in required_env.items() if not value]
    if missing:
        raise RuntimeError(f"Missing X credentials: {', '.join(missing)}")

    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    authorization = _oauth1_authorization_header(
        "POST",
        X_CREATE_POST_URL,
        required_env["X_API_KEY"],
        required_env["X_API_SECRET"],
        required_env["X_ACCESS_TOKEN"],
        required_env["X_ACCESS_TOKEN_SECRET"],
    )
    request = Request(
        X_CREATE_POST_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "KianiExchange-XPublisher/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"X API returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not create X post: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise RuntimeError("X API returned an unexpected response")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Kiani Exchange rates to X")
    parser.add_argument("--dry-run", action="store_true", help="Print output without publishing")
    parser.add_argument(
        "--mode",
        choices=("publish", "alert"),
        default="publish",
        help="Publish a rate table or check for a significant rate-change alert",
    )
    parser.add_argument(
        "--variant",
        choices=tuple(POST_TITLES),
        default="standard",
        help="Time-of-day wording for regular rate posts",
    )
    parser.add_argument(
        "--no-link",
        action="store_true",
        help="Omit miniapp.kiani.exchange but keep the WhatsApp link",
    )
    parser.add_argument(
        "--no-links",
        action="store_true",
        help="Omit both the WhatsApp and mini-app URLs",
    )
    parser.add_argument(
        "--state-file",
        default=os.getenv("X_RATE_STATE_FILE", ".x-rate-state/latest.json"),
        help="Persistent state used to compare against the last published rates",
    )
    parser.add_argument(
        "--alert-threshold",
        type=Decimal,
        default=Decimal(os.getenv("X_RATE_ALERT_THRESHOLD", "0.5")),
        help="Minimum absolute percentage movement that triggers an alert (default: 0.5)",
    )
    args = parser.parse_args()

    rates_url = os.getenv("KIANI_RATES_URL", DEFAULT_RATES_URL).strip() or DEFAULT_RATES_URL
    rates = fetch_current_rates(rates_url)

    if args.mode == "alert":
        previous = load_rate_state(args.state_file)
        if previous is None or not all(key in previous for key in ALERT_RATE_KEYS):
            if args.dry_run:
                print("No previous published-rate state exists; alert baseline would be initialized.")
            else:
                save_rate_state(args.state_file, rates)
                print("Initialized rate-alert baseline; no X post created.")
            return 0

        changes = calculate_significant_changes(previous, rates, args.alert_threshold)
        if not changes:
            print(f"No rate movement reached the {args.alert_threshold}% alert threshold.")
            return 0

        text = build_alert_text(changes)
        if args.dry_run:
            print(text)
            return 0

        result = publish_to_x(text)
        save_rate_state(args.state_file, rates)
        post_id = result["data"].get("id", "unknown")
        print(f"Published Kiani Exchange rate alert to X (post id: {post_id})")
        return 0

    include_whatsapp = not args.no_links
    include_miniapp = not (args.no_link or args.no_links)
    text = build_post_text(
        rates,
        include_link=include_miniapp,
        include_whatsapp=include_whatsapp,
        variant=args.variant,
    )

    if args.dry_run:
        print(text)
        return 0

    result = publish_to_x(text)
    save_rate_state(args.state_file, rates)
    post_id = result["data"].get("id", "unknown")
    print(f"Published Kiani Exchange rates to X (post id: {post_id})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
