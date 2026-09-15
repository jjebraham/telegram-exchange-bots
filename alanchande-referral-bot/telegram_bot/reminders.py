from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

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
    if result == "created":
        text = (
            "🎉 <b>یک نفر جدید با لینک تو عضو شد!</b>\n\n"
            "⭐ از همین حالا در امتیاز موقتت حساب می‌شود.\n"
            f"🎟 اگر <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته بماند، "
            "به بلیت تأییدشده قرعه‌کشی تبدیل می‌شود."
        )
    else:
        text = (
            "🔄 <b>یکی از دعوت‌شده‌هات دوباره عضو شد.</b>\n\n"
            "⏳ زمان تأیید او از صفر شروع شد و تا وقتی عضو بماند دوباره در امتیاز موقتت حساب می‌شود."
        )
    try:
        await application.bot.send_message(referrer_id, text, parse_mode=ParseMode.HTML)
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify referrer %s from reconciliation worker", referrer_id)


async def _finalize_row(application: Application, campaign, row: dict, source: str) -> bool:
    db: ReferralDB = application.bot_data["db"]
    user_id = int(row["joined_user_id"])
    result, referrer_id = db.finalize_pending_join(
        campaign,
        user_id,
        row.get("joined_username"),
        row.get("joined_first_name"),
    )
    if referrer_id is None:
        return False
    if result in {"created", "reactivated"}:
        await _notify_referrer(application, campaign, referrer_id, result)
        db.track_funnel_event(campaign.id, user_id, "join_confirmed", source)
        try:
            from .referral_success import send_participant_welcome
            fake_user = SimpleNamespace(
                id=user_id,
                username=row.get("joined_username"),
                first_name=row.get("joined_first_name") or "دوست عزیز",
                last_name=None,
            )
            # Build a lightweight PTB-like context wrapper for the shared onboarding function.
            fake_context = SimpleNamespace(
                bot=application.bot,
                application=application,
                bot_data=application.bot_data,
            )
            await send_participant_welcome(fake_context, campaign, fake_user)
        except Exception:
            log.exception("Could not onboard reconciled referral user=%s", user_id)
        return True
    return result in {"duplicate", "already_recorded"}


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
            if await _finalize_row(application, campaign, row, "reminder"):
                db.track_funnel_event(campaign.id, user_id, "reminder_converted", "")
            continue

        text = (
            "⏰ <b>لینک دعوتت هنوز منتظر تکمیل عضویته.</b>\n\n"
            "1️⃣ روی «ورود به کانال و عضویت» بزن.\n"
            "2️⃣ داخل کانال روی «Join Channel / عضویت» بزن.\n"
            "3️⃣ بعد به <b>همین چت</b> برگرد و «✅ عضو شدم؛ بررسی کن» را بزن.\n\n"
            "🎁 بعد از عضویت، خودت هم لینک اختصاصی می‌گیری و می‌تونی دوستات رو دعوت کنی."
        )
        try:
            await application.bot.send_message(
                user_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=_pending_keyboard(settings, campaign.id),
            )
            db.mark_pending_reminder_sent(campaign.id, user_id)
            db.track_funnel_event(campaign.id, user_id, "reminder_sent", "")
            log.info("Sent pending referral reminder to user=%s campaign=%s", user_id, campaign.slug)
        except (Forbidden, BadRequest):
            db.mark_pending_reminder_sent(campaign.id, user_id)
        except TelegramError:
            log.exception("Could not send pending referral reminder to user=%s", user_id)


async def reconciliation_pass(application: Application) -> None:
    """Heal missed pending-join and currently-left membership events without changing rules."""
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return

    for row in db.pending_reconciliation_candidates(
        campaign.id, limit=settings.reconciliation_batch_size
    ):
        user_id = int(row["joined_user_id"])
        try:
            if await telegram_membership(application.bot, settings, user_id):
                await _finalize_row(application, campaign, row, "reconciliation")
        except TelegramError:
            log.warning("Pending reconciliation lookup failed user=%s", user_id)
        await asyncio.sleep(0.05)

    for row in db.active_referrals_for_reconciliation(
        campaign.id, limit=settings.reconciliation_batch_size
    ):
        user_id = int(row["joined_user_id"])
        try:
            if not await telegram_membership(application.bot, settings, user_id):
                changed = db.mark_left(user_id)
                if changed:
                    log.info("Reconciliation marked referral left: user=%s rows=%s", user_id, changed)
        except TelegramError:
            log.warning("Active reconciliation lookup failed user=%s", user_id)
        await asyncio.sleep(0.05)


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


async def reconciliation_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    while True:
        try:
            await reconciliation_pass(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Membership reconciliation worker failed")
        await asyncio.sleep(settings.reconciliation_check_seconds)


async def post_init(application: Application) -> None:
    await user_post_init(application)
    application.bot_data["pending_reminder_task"] = asyncio.create_task(
        pending_reminder_loop(application), name="pending-referral-reminder-loop"
    )
    application.bot_data["reconciliation_task"] = asyncio.create_task(
        reconciliation_loop(application), name="membership-reconciliation-loop"
    )


async def post_stop(application: Application) -> None:
    for key in ("pending_reminder_task", "reconciliation_task"):
        task = application.bot_data.get(key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await user_post_stop(application)
