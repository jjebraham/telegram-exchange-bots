from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application

from referral_core import ReferralDB
from referral_core.models import utcnow
from .config import Settings, hours_label, telegram_membership
from .user_handlers import post_init as user_post_init, post_stop as user_post_stop

log = logging.getLogger("alanchande_referral_bot")


def _pending_keyboard(settings: Settings, campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ ورود به کانال و عضویت", url=settings.channel_url)],
        [InlineKeyboardButton("✅ عضو شدم؛ بررسی کن", callback_data=f"ref:check:{campaign_id}")],
    ])


async def _notify_referrer(application: Application, campaign, referrer_id: int, result: str) -> None:
    if result not in {"created", "reactivated"}:
        return
    try:
        await application.bot.send_message(
            referrer_id,
            f"🎉 یک نفر با لینک تو عضو شد!\n\n⏳ اگر <b>{hours_label(campaign.min_stay_hours)}</b> "
            "پیوسته در کانال بماند، دعوت او تأیید می‌شود.",
            parse_mode=ParseMode.HTML,
        )
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify referrer %s from reminder worker", referrer_id)


async def pending_reminder_pass(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return

    cutoff = utcnow() - timedelta(minutes=settings.pending_reminder_minutes)
    rows = db.pending_reminder_candidates(campaign.id, cutoff, limit=100)

    for row in rows:
        user_id = int(row["joined_user_id"])
        try:
            is_member = await telegram_membership(application.bot, settings, user_id)
        except TelegramError:
            log.exception("Reminder membership check failed for user=%s", user_id)
            continue

        if is_member:
            referrer_id = db.pop_pending_referrer(campaign.id, user_id)
            if referrer_id is None:
                continue
            result = db.record_join(
                campaign,
                user_id,
                referrer_id,
                row.get("joined_username"),
                row.get("joined_first_name"),
            )
            await _notify_referrer(application, campaign, referrer_id, result)
            log.info(
                "Reminder worker finalized referral: joined=%s referrer=%s campaign=%s",
                user_id, referrer_id, campaign.slug,
            )
            continue

        text = (
            "⏰ <b>عضویتت هنوز کامل نشده.</b>\n\n"
            "برای اینکه دعوتت ثبت شود:\n"
            "1️⃣ روی «ورود به کانال و عضویت» بزن.\n"
            "2️⃣ داخل کانال روی «Join Channel / عضویت» بزن.\n"
            "3️⃣ برگرد و «✅ عضو شدم؛ بررسی کن» را بزن.\n\n"
            "🎁 بعد از عضویت، خودت هم می‌توانی با /start لینک اختصاصی بگیری، "
            "دوستانت را دعوت کنی و در قرعه‌کشی شرکت کنی."
        )
        try:
            await application.bot.send_message(
                user_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=_pending_keyboard(settings, campaign.id),
            )
            db.mark_pending_reminder_sent(campaign.id, user_id)
            log.info("Sent pending referral reminder to user=%s campaign=%s", user_id, campaign.slug)
        except (Forbidden, BadRequest):
            # Do not retry forever if the user blocked the bot or the chat is unavailable.
            db.mark_pending_reminder_sent(campaign.id, user_id)
        except TelegramError:
            log.exception("Could not send pending referral reminder to user=%s", user_id)


async def pending_reminder_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    while True:
        try:
            await pending_reminder_pass(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Pending referral reminder worker failed")
        await asyncio.sleep(settings.pending_reminder_check_seconds)


async def post_init(application: Application) -> None:
    await user_post_init(application)
    application.bot_data["pending_reminder_task"] = asyncio.create_task(
        pending_reminder_loop(application), name="pending-referral-reminder-loop"
    )


async def post_stop(application: Application) -> None:
    task = application.bot_data.get("pending_reminder_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await user_post_stop(application)
