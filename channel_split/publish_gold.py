#!/usr/bin/env python3
"""Preview or publish the AlanChande Turkish-gold post."""

from __future__ import annotations

import argparse
import sys

from gold_prices import build_turkish_gold_post, fetch_turkish_gold_quotes
from publish_channels import _load_local_env, _required_env, telegram_send


def main() -> int:
    _load_local_env()

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print instead of sending to Telegram")
    args = parser.parse_args()

    quotes = fetch_turkish_gold_quotes()
    text = build_turkish_gold_post(quotes)

    if args.dry_run:
        print(text)
        return 0

    token = _required_env("ALANCHANDE_TELEGRAM_BOT_TOKEN")
    chat_id = _required_env("ALANCHANDE_CHANNEL_ID")
    telegram_send(token, chat_id, text)
    print("sent -> ALANCHANDE_CHANNEL_ID using ALANCHANDE_TELEGRAM_BOT_TOKEN")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
