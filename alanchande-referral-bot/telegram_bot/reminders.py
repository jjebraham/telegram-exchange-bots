from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application

from referral_core import ReferralDB, points_from_invites
from referral_core.models import utcnow
from .config import Settings, hours_label, telegram_membership
from .user_handlers import post_init as user_post_init, post_stop as user_post_stop

log = logging.getLogger("alanchande_referral_bot")


def _pending_keyboard(settings: Settings, campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ ورود به کانال و عضویت", url=settings.channel_url)],
        [InlineKeyboardButton("✅ عضو شدم؛ بررسی کن", callback_data=f"ref:check:{campaign_id}")],
    ])


def _notification_allowed(application: Application, campaign_id: int, user_id: int) -> bool:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    return db.notification_gate(
        campaign_id,
        user_id,
        settings.notification_max_per_window,
        settings.notification_window_seconds,
    )


async def _notify_referrer(application: Application, campaign, referrer_id: int, result: str) -> None:
    if result not in {"created", "reactivated"}:
        return
    db: ReferralDB = application.bot_data["db"]
    counts = db.campaign_counts(campaign, referrer_id)
    previous_current = points_from_invites(
        max(0, counts["active"] - 1), campaign.invites_per_point, campaign.max_points
    )
    gained_point = counts["current_points"] > previous_current
    remainder = counts["active"] % campaign.invites_per_point
    need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point
    milestone = "\n🎉 <b>یک امتیاز موقت جدید گرفتی!</b>" if gained_point else ""

    if result == "created":
        text = (
            "🎉 <b>یک نفر جدید با لینک تو عضو شد!</b>\n\n"
            f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>{milestone}\n"
            f"🔥 تا امتیاز موقت بعدی: <b>{need}</b> دعوت فعال\n\n"
            f"🎟 اگر <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته بماند، "
            "به بلیت تأییدشده قرعه‌کشی تبدیل می‌شود."
        )
    else:
        text = (
            "🔄 <b>یکی از دعوت‌شده‌هات دوباره عضو شد.</b>\n\n"
            "⏳ زمان تأیید او از صفر شروع شد.\n"
            f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>{milestone}"
        )
    if not _notification_allowed(application, campaign.id, referrer_id):
        log.info("Throttled referral notification referrer=%s campaign=%s", referrer_id, campaign.slug)
        return
    try:
        await application.bot.send_message(referrer_id, text, parse_mode=ParseMode.HTML)
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify referrer %s from reconciliation worker", referrer_id)


async def _notify_reconciled_leave(application: Application, campaign, referrer_id: int) -> None:
    db: ReferralDB = application.bot_data["db"]
    counts = db.campaign_counts(campaign, referrer_id)
    previous_current = points_from_invites(
        counts["active"] + 1, campaign.invites_per_point, campaign.max_points
    )
    lost_point = counts["current_points"] < previous_current
    score_line = "\n⬇️ <b>یک امتیاز موقت کم شد.</b>" if lost_point else ""
    if not _notification_allowed(application, campaign.id, referrer_id):
        return
    try:
        await application.bot.send_message(
            referrer_id,
            "❌ <b>در بررسی دوره‌ای مشخص شد یکی از دعوت‌شده‌هات دیگر عضو کانال نیست.</b>\n\n"
            f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>{score_line}\n"
            "اگر دوباره عضو شود، زمان تأییدش از صفر شروع می‌شود.",
            parse_mode=ParseMode.HTML,
        )
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify reconciled leave referrer=%s", referrer_id)


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


async def pending_reminder_pass(application: Application) -> dict:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None, "checked": 0, "sent": 0, "converted": 0}

    cutoff = utcnow() - timedelta(minutes=settings.pending_reminder_minutes)
    rows = db.pending_reminder_candidates(campaign.id, cutoff, limit=100)
    sent = converted = 0

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
                converted += 1
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
            sent += 1
            log.info("Sent pending referral reminder to user=%s campaign=%s", user_id, campaign.slug)
        except (Forbidden, BadRequest):
            db.mark_pending_reminder_sent(campaign.id, user_id)
        except TelegramError:
            log.exception("Could not send pending referral reminder to user=%s", user_id)
    return {"campaign": campaign.slug, "checked": len(rows), "sent": sent, "converted": converted}


async def reconciliation_pass(application: Application) -> dict:
    """Heal missed pending-join and leave events without changing contest rules."""
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None, "pending_checked": 0, "active_checked": 0, "fixed": 0, "left": 0, "errors": 0}

    pending_checked = active_checked = fixed = left_count = errors = 0
    for row in db.pending_reconciliation_candidates(
        campaign.id, limit=settings.reconciliation_batch_size
    ):
        pending_checked += 1
        user_id = int(row["joined_user_id"])
        try:
            if await telegram_membership(application.bot, settings, user_id):
                if await _finalize_row(application, campaign, row, "reconciliation"):
                    fixed += 1
        except TelegramError:
            errors += 1
            log.warning("Pending reconciliation lookup failed user=%s", user_id)
        await asyncio.sleep(0.05)

    for row in db.active_referrals_for_reconciliation(
        campaign.id, limit=settings.reconciliation_batch_size
    ):
        active_checked += 1
        user_id = int(row["joined_user_id"])
        referrer_id = int(row["referrer_id"])
        try:
            if not await telegram_membership(application.bot, settings, user_id):
                changed = db.mark_left(user_id)
                if changed:
                    left_count += changed
                    log.info("Reconciliation marked referral left: user=%s rows=%s", user_id, changed)
                    db.track_funnel_event(campaign.id, user_id, "left", "reconciliation")
                    await _notify_reconciled_leave(application, campaign, referrer_id)
        except TelegramError:
            errors += 1
            log.warning("Active reconciliation lookup failed user=%s", user_id)
        await asyncio.sleep(0.05)
    return {
        "campaign": campaign.slug,
        "pending_checked": pending_checked,
        "active_checked": active_checked,
        "fixed": fixed,
        "left": left_count,
        "errors": errors,
    }


async def analytics_snapshot_pass(application: Application) -> dict:
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None}
    metrics = db.capture_daily_metrics(campaign)
    return {"campaign": campaign.slug, **metrics}


async def nudge_pass(application: Application) -> dict:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None, "zero_referral": 0, "promo_abandon": 0, "summaries": 0}

    zero_rows = db.zero_referral_nudge_candidates(
        campaign.id,
        utcnow() - timedelta(hours=settings.zero_referral_nudge_hours),
        limit=100,
    )
    zero_sent = 0
    for row in zero_rows:
        uid = int(row["user_id"])
        try:
            await application.bot.send_message(
                uid,
                "🔥 <b>هنوز اولین دعوتت ثبت نشده.</b>\n\n"
                "لینک اختصاصی‌ات آماده است؛ برای چند نفر از دوستات بفرست تا اولین امتیازت رو شروع کنی. 👇",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 دیدن و فرستادن لینک دعوت", callback_data="menu:link")]
                ]),
            )
            zero_sent += 1
            db.track_funnel_event(campaign.id, uid, "nudge_zero_referral_sent", "")
        except (Forbidden, BadRequest):
            db.track_funnel_event(campaign.id, uid, "nudge_zero_referral_sent", "unreachable")
        except TelegramError:
            log.exception("Zero-referral nudge failed user=%s", uid)

    promo_rows = db.promo_abandon_nudge_candidates(
        campaign.id,
        utcnow() - timedelta(hours=settings.promo_abandon_nudge_hours),
        limit=100,
    )
    promo_sent = 0
    for row in promo_rows:
        uid = int(row["user_id"])
        source = str(row.get("source") or "promo")
        try:
            await application.bot.send_message(
                uid,
                "🎁 <b>شرکت در مسابقه‌ات هنوز کامل نشده.</b>\n\n"
                "اگر هنوز می‌خوای شرکت کنی، عضو کانال شو و بعد روی دکمه زیر بزن تا لینک اختصاصی‌ات ساخته بشه.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 عضویت در کانال", url=settings.channel_url)],
                    [InlineKeyboardButton("🚀 تکمیل شرکت در مسابقه", callback_data=f"promo:enter:{campaign.id}")],
                ]),
            )
            promo_sent += 1
            db.track_funnel_event(campaign.id, uid, "nudge_promo_abandon_sent", source)
        except (Forbidden, BadRequest):
            db.track_funnel_event(campaign.id, uid, "nudge_promo_abandon_sent", "unreachable")
        except TelegramError:
            log.exception("Promo-abandon nudge failed user=%s", uid)

    due = db.notification_summaries_due(
        campaign.id,
        utcnow() - timedelta(seconds=settings.notification_window_seconds),
        limit=100,
    )
    summaries = 0
    for row in due:
        uid = int(row["user_id"])
        count = int(row["suppressed_count"])
        try:
            await application.bot.send_message(
                uid,
                f"🔔 در مدت کوتاهی <b>{count}</b> تغییر دیگر در دعوت‌هات ثبت شد.\n\n"
                "برای دیدن وضعیت به‌روز، /me رو بزن.",
                parse_mode=ParseMode.HTML,
            )
            summaries += 1
            db.clear_notification_summary(campaign.id, uid)
        except (Forbidden, BadRequest):
            db.clear_notification_summary(campaign.id, uid)
        except TelegramError:
            log.exception("Notification summary failed user=%s", uid)

    return {
        "campaign": campaign.slug,
        "zero_referral": zero_sent,
        "promo_abandon": promo_sent,
        "summaries": summaries,
    }


async def pending_reminder_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    while True:
        try:
            details = await pending_reminder_pass(application)
            db.set_maintenance_status("pending_reminder", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("pending_reminder", False, error=str(exc))
            log.exception("Pending referral reminder worker failed")
        await asyncio.sleep(settings.pending_reminder_check_seconds)


async def reconciliation_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    while True:
        try:
            details = await reconciliation_pass(application)
            db.set_maintenance_status("reconciliation", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("reconciliation", False, error=str(exc))
            log.exception("Membership reconciliation worker failed")
        await asyncio.sleep(settings.reconciliation_check_seconds)


async def analytics_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    while True:
        try:
            details = await analytics_snapshot_pass(application)
            db.set_maintenance_status("analytics_snapshot", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("analytics_snapshot", False, error=str(exc))
            log.exception("Analytics snapshot worker failed")
        await asyncio.sleep(settings.analytics_snapshot_seconds)


async def nudge_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    while True:
        try:
            details = await nudge_pass(application)
            db.set_maintenance_status("nudges", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("nudges", False, error=str(exc))
            log.exception("Nudge/notification-summary worker failed")
        await asyncio.sleep(settings.nudge_check_seconds)


async def post_init(application: Application) -> None:
    await user_post_init(application)
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


async def post_stop(application: Application) -> None:
    for key in (
        "pending_reminder_task", "reconciliation_task", "analytics_task", "nudge_task"
    ):
        task = application.bot_data.get(key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await user_post_stop(application)
