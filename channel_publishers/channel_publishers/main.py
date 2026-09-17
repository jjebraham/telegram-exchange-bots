from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .providers import DovizComBankRatesProvider, RateSourceError
from .renderers import render_bank_comparison, render_kiani_rates
from .telegram_client import TelegramPublishError, send_html_message


DEFAULT_INSTITUTIONS = [
    "Kapalıçarşı",
    "Garanti BBVA",
    "İş Bankası",
    "Kuveyt Türk",
    "Ziraat Bankası",
]


def _post_or_preview(*, text: str, dry_run: bool, enabled: bool, bot_token: str, channel_id: str, timeout: float) -> None:
    print(text)
    if dry_run:
        return
    if not enabled:
        raise RuntimeError("POSTING_ENABLED is false; refusing to publish")
    send_html_message(bot_token=bot_token, chat_id=channel_id, text=text, timeout=timeout)


def run_bank_comparison(currency: str, dry_run: bool) -> None:
    settings = load_settings()
    if settings.bank_rates_provider != "doviz_com":
        raise RuntimeError(f"Unsupported BANK_RATES_PROVIDER: {settings.bank_rates_provider}")

    provider = DovizComBankRatesProvider(
        timeout=settings.timeout_seconds,
        user_agent=settings.user_agent,
    )
    rates = provider.get_rates(currency, DEFAULT_INSTITUTIONS)
    text = render_bank_comparison(rates, currency)
    _post_or_preview(
        text=text,
        dry_run=dry_run,
        enabled=settings.posting_enabled,
        bot_token=settings.alanchande_bot_token,
        channel_id=settings.alanchande_channel_id,
        timeout=settings.timeout_seconds,
    )


def run_kiani_rates(dry_run: bool) -> None:
    settings = load_settings()
    if not settings.kiani_rates:
        raise RuntimeError(
            "KIANI_RATES_JSON is empty. For the test phase provide a JSON rate snapshot; "
            "production pricing will be wired through a dedicated adapter next."
        )
    text = render_kiani_rates(settings.kiani_rates)
    _post_or_preview(
        text=text,
        dry_run=dry_run,
        enabled=settings.posting_enabled,
        bot_token=settings.kiani_bot_token,
        channel_id=settings.kiani_channel_id,
        timeout=settings.timeout_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AlanChande / Kiani Telegram channel publisher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bank = subparsers.add_parser("bank-comparison", help="Publish/preview a Turkish bank FX comparison")
    bank.add_argument("--currency", default="USD", choices=["USD", "EUR", "GBP"])
    bank.add_argument("--dry-run", action="store_true")

    kiani = subparsers.add_parser("kiani-rates", help="Publish/preview a Kiani buy/sell card")
    kiani.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "bank-comparison":
            run_bank_comparison(args.currency, args.dry_run)
        elif args.command == "kiani-rates":
            run_kiani_rates(args.dry_run)
        return 0
    except (RateSourceError, TelegramPublishError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
