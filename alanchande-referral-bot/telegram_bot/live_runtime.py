from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from referral_core import ReferralDB
from .config import Settings, extract_status_change, is_configured_channel
from .context import services
from .growth import daily_admin_digest_loop
from .reminders import analytics_loop, nudge_loop, pending_reminder_loop, reconciliation_loop
from .share_activation import install_zero_open_nudge_filter
from .user_handlers import notify_referral_join

log = logging.getLogger("alanchande_referral_bot")


def _allowed(settings: Settings, db: ReferralDB, campaign_id: int, user_id: int) -> bool:
    return db.notification_gate(
        campaign_id,
        user_id,
        settings.notification_max_per_window,
        settings.notification_window_seconds,
    )


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    cmu = update.chat_member
    if cmu is None or not is_configured_channel(cmu.chat, settings):
        return
    was_member, is_member_now = extract_status_change(cmu)
    user = cmu.new_chat_member.user
    if getattr(user, "is_bot", False):
        return

    if not was_member and is_member_now:
        campaign = db.live_campaign()
        if not campaign:
            return
        db.upsert_user(user.id, user.username, user.first_name, user.last_name)
        result, referrer_id = db.finalize_pending_join(
            campaign, user.id, user.username, user.first_name,
        )
        if referrer_id is not None and result in {"created", "reactivated"}:
            if _allowed(settings, db, campaign.id, referrer_id):
                await notify_referral_join(context, campaign, user, referrer_id, result)
            else:
                event_type = "join_confirmed" if result == "created" else "rejoin"
                db.track_funnel_event(campaign.id, user.id, event_type, "throttled")
            from .referral_success import send_participant_welcome
            await send_participant_welcome(context, campaign, user)
            return

        referrer_id = db.reactivate_original(
            campaign.id, user.id, user.username, user.first_name,
        )
        if referrer_id is not None:
            if _allowed(settings, db, campaign.id, referrer_id):
                await notify_referral_join(context, campaign, user, referrer_id, "reactivated")
            else:
                db.track_funnel_event(campaign.id, user.id, "rejoin", "throttled")
            from .referral_success import send_participant_welcome
            await send_participant_welcome(context, campaign, user)

    elif was_member and not is_member_now:
        campaign = db.live_campaign()
        referrer_id = db.referrer_for_joined(campaign.id, user.id) if campaign else None
        changed = db.mark_left(user.id)
        if changed:
            log.info("Referral member left: user=%s records=%s", user.id, changed)
            if campaign:
                db.track_funnel_event(campaign.id, user.id, "left", "")
            if campaign and referrer_id is not None and _allowed(
                settings, db, campaign.id, referrer_id
            ):
                counts = db.campaign_counts(campaign, referrer_id)
                try:
                    await context.bot.send_message(
                        referrer_id,
                        "❌ <b>یکی از دعوت‌شده‌هات از کانال خارج شد.</b>\n\n"
                        f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>\n"
                        "اگر دوباره عضو شود، زمان تأییدش از صفر شروع می‌شود.",
                        parse_mode=ParseMode.HTML,
                    )
                except (Forbidden, BadRequest):
                    pass
                except TelegramError:
                    log.exception("Could not send referral-left notice referrer=%s", referrer_id)


async def qualification_pass(application: Application) -> dict:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None, "processed": 0, "suppressed": 0}
    processed = suppressed = 0
    for row in db.unnotified_qualified(campaign, limit=100):
        counts = db.campaign_counts(campaign, row["referrer_id"])
        allowed = _allowed(settings, db, campaign.id, int(row["referrer_id"]))
        if allowed:
            name = escape(row["joined_first_name"] or "دوستت")
            try:
                await application.bot.send_message(
                    row["referrer_id"],
                    f"🎟 دعوت <b>{name}</b> تأیید شد!\n\n"
                    f"✅ دعوت‌های تأییدشده: <b>{counts['qualified']}</b>\n"
                    f"🎟 بلیت‌های تأییدشده قرعه‌کشی: <b>{counts['confirmed_points']}</b>\n"
                    f"⭐ امتیاز موقت فعلی: <b>{counts['current_points']}</b>\n\n"
                    "🏆 این دعوت حالا واقعاً در قرعه‌کشی نهایی حساب می‌شود.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📤 دعوت نفر بعدی", callback_data="menu:link"),
                        InlineKeyboardButton("📊 وضعیت من", callback_data="menu:stats"),
                    ]]),
                )
            except (Forbidden, BadRequest):
                pass
            except TelegramError:
                log.exception("Qualification notification failed for referral %s", row["id"])
                continue
        else:
            suppressed += 1
        db.mark_qualification_notified(row["id"])
        db.track_funnel_event(campaign.id, row["joined_user_id"], "qualified", "")
        processed += 1
    return {"campaign": campaign.slug, "processed": processed, "suppressed": suppressed}


async def qualification_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    while True:
        try:
            details = await qualification_pass(application)
            db.set_maintenance_status("qualification", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("qualification", False, error=str(exc))
            log.exception("Qualification worker failed")
        await asyncio.sleep(settings.qualification_check_seconds)


async def post_init(application: Application) -> None:
    # Keep the existing nudge worker, but make its 2-hour candidate query mean
    # exactly "personal link has produced zero observable opens". This preserves
    # the 24-hour and promo-abandon nudges without running a second nudge loop.
    install_zero_open_nudge_filter()

    application.bot_data["qualification_task"] = asyncio.create_task(
        qualification_loop(application), name="qualification-loop"
    )
    application.bot_data["pending_reminder_task"] = asyncio.create_task(
        pending_reminder_loop(application), name="pending-referral-reminder-loop"
    )
    application.bot_data["reconciliation_task"] = asyncio.create_task(
        reconciliation_loop(application), name="membership-reconciliation-loop"
    )
    application.bot_data["analytics_task"] = asyncio.create_task(
        analytics_loop(application), name="analytics-snapshot-loop"
    )
    application.bot_data["nudge_task"] = asyncio.create_task(
        nudge_loop(application), name="participant-nudge-loop"
    )
    application.bot_data["daily_digest_task"] = asyncio.create_task(
        daily_admin_digest_loop(application), name="daily-admin-digest-loop"
    )


async def post_stop(application: Application) -> None:
    for key in (
        "qualification_task", "pending_reminder_task", "reconciliation_task",
        "analytics_task", "nudge_task", "daily_digest_task",
    ):
        task = application.bot_data.get(key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
