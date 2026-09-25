#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from referral_core import ReferralDB
from telegram_bot.config import Settings
from telegram_bot.growth import build_promo_link, normalize_promo_source

ISTANBUL = ZoneInfo("Europe/Istanbul")
DEFAULT_ENV = ROOT / ".env"
DEFAULT_IMAGE = ROOT / "assets" / "meditation-autumn-20260925.png"

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_number(value: int) -> str:
    return str(int(value)).translate(_FA_DIGITS)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def unique_source(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(ISTANBUL)).strftime("%Y%m%d_%H%M%S")
    return normalize_promo_source(f"meditation_{stamp}")


def build_caption(*, participants: int, winners: int, deadline_fa: str) -> str:
    return (
        "🎁 یه هدیه کوچیک برای همراه‌های این کانال\n\n"
        "قرعه‌کشی رایگان پاییز — ۲۱ میلیون تومان جایزه نقدی\n"
        "🥇 ۱۰ میلیون\n"
        "🥈 ۵ میلیون\n"
        "🥉 سه نفر، هر کدوم ۲ میلیون\n\n"
        f"🎟 تا این لحظه فقط {fa_number(participants)} بلیت ثبت شده و "
        f"{fa_number(winners)} جایزه داریم\n"
        f"⏳ آخرین فرصت دعوت: {deadline_fa}\n\n"
        "👇 شرکت رایگان"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish one tracked AlanChande promo photo to the meditation channel."
    )
    parser.add_argument(
        "--env",
        default=str(DEFAULT_ENV),
        help="Path to the referral-bot .env file.",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Telegram channel @username or numeric -100... ID. Defaults to MEDITATION_CHANNEL_ID.",
    )
    parser.add_argument(
        "--image",
        default=None,
        help="Image path. Defaults to MEDITATION_PROMO_IMAGE or the standard assets path.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional source base. Default is a unique meditation_YYYYMMDD_HHMMSS source.",
    )
    parser.add_argument(
        "--deadline-fa",
        default=None,
        help="Persian display deadline. Defaults to MEDITATION_INVITE_DEADLINE_FA or ۱۷ مهر.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated source, link and caption without publishing.",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    load_env_file(Path(args.env).expanduser())

    settings = Settings.from_env()

    posting_token = os.environ.get("MEDITATION_POSTING_BOT_TOKEN", "").strip() or settings.bot_token
    campaign_bot_username = (
        os.environ.get("CAMPAIGN_BOT_USERNAME", "").strip().lstrip("@")
        or "Alanchandebot"
    )

    channel = (
        args.channel
        or os.environ.get("MEDITATION_CHANNEL_ID", "").strip()
    )
    if not channel:
        raise SystemExit(
            "MEDITATION_CHANNEL_ID is required (use @channel_username or numeric -100... ID)."
        )
    channel_ref: int | str
    try:
        channel_ref = int(channel)
    except ValueError:
        channel_ref = channel if channel.startswith("@") else f"@{channel}"

    image = Path(
        args.image
        or os.environ.get("MEDITATION_PROMO_IMAGE", "").strip()
        or DEFAULT_IMAGE
    ).expanduser()
    if not image.is_file():
        raise SystemExit(f"Promo image not found: {image}")

    deadline_fa = (
        args.deadline_fa
        or os.environ.get("MEDITATION_INVITE_DEADLINE_FA", "").strip()
        or "۱۷ مهر"
    )

    db = ReferralDB(settings.db_path)
    db.init()
    campaign = db.live_campaign()
    if not campaign:
        raise SystemExit("No live campaign.")

    stats = db.admin_stats(campaign)
    participants = int(stats["participants"])
    source = normalize_promo_source(args.source) if args.source else unique_source()

    async with Bot(posting_token) as bot:
        me = await bot.get_me()
        if not me.username:
            raise SystemExit("Posting bot username is unavailable.")
        promo_link = build_promo_link(campaign_bot_username, source, "b")
        caption = build_caption(
            participants=participants,
            winners=int(campaign.num_winners),
            deadline_fa=deadline_fa,
        )

        print(f"campaign={campaign.slug}")
        print(f"source={source}_b")
        print(f"participants={participants}")
        print(f"link={promo_link}")
        print(f"image={image}")
        print(f"posting_bot=@{me.username}")
        print(f"campaign_bot=@{campaign_bot_username}")
        print(f"channel={channel_ref}")

        if args.dry_run:
            print("\n--- caption ---\n")
            print(caption)
            return

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 شرکت رایگان", url=promo_link)]
        ])

        with image.open("rb") as photo:
            sent = await bot.send_photo(
                chat_id=channel_ref,
                photo=photo,
                caption=caption,
                reply_markup=keyboard,
            )

        print(f"published_message_id={sent.message_id}")


if __name__ == "__main__":
    asyncio.run(run())
