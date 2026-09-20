from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application

from referral_core import ReferralDB, points_from_invites
from referral_core.models import parse_datetime, utcnow
from .config import Settings, hours_label, remaining_label, telegram_membership
from .ui import link_keyboard
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


def _early_share_nudge_candidates(db: ReferralDB, campaign_id: int, cutoff, limit: int = 100) -> list[dict]:
    """Participants with a link but no pending/joined referral and no early share nudge yet."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT l.user_id,l.invite_link,l.created_at
               FROM invite_links l
               WHERE l.campaign_id=? AND l.created_at<=?
                 AND EXISTS (
                     SELECT 1 FROM funnel_events e
                     WHERE e.campaign_id=l.campaign_id AND e.user_id=l.user_id
                       AND e.event_type='entered_contest'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM pending_referrals p
                     WHERE p.campaign_id=l.campaign_id AND p.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM referrals r
                     WHERE r.campaign_id=l.campaign_id AND r.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM funnel_events e
                     WHERE e.campaign_id=l.campaign_id AND e.user_id=l.user_id
                       AND e.event_type='nudge_early_share_sent'
                 )
               ORDER BY l.created_at ASC
               LIMIT ?""",
            (campaign_id, cutoff.isoformat(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _participant_first_touch_source(db: ReferralDB, campaign_id: int, user_id: int) -> str:
    """Return the participant's earliest tracked bot-start source."""
    with db.connect() as conn:
        row = conn.execute(
            """SELECT source FROM funnel_events
               WHERE campaign_id=? AND user_id=? AND event_type='bot_start'
               ORDER BY created_at ASC, rowid ASC
               LIMIT 1""",
            (campaign_id, user_id),
        ).fetchone()
    return str(row["source"] or "organic") if row else "legacy/untracked"


def _early_share_nudge_text(campaign, source: str) -> str:
    if source == "referral":
        return (
            "🔁 <b>تو هم می‌تونی زنجیره دعوت رو ادامه بدی.</b>\n\n"
            "خودت با لینک یکی از دوستات وارد شدی و حالا لینک اختصاصی خودت آماده است.\n"
            f"🎯 برای اولین امتیاز موقت به <b>{campaign.invites_per_point}</b> دعوت فعال نیاز داری.\n"
            "همین الان فقط برای ۲ نفر از دوستات بفرستش؛ وقتی اولین نفر لینک رو باز کنه، همینجا بهت خبر می‌دیم. 🚀"
        )
    return (
        "📤 <b>لینک دعوتت هنوز برای کسی باز نشده.</b>\n\n"
        f"🎯 برای اولین امتیاز موقت به <b>{campaign.invites_per_point}</b> دعوت فعال نیاز داری.\n"
        "همین الان لینک رو برای ۲–۳ نفر بفرست؛ وقتی اولین نفر بازش کنه، همینجا بهت خبر می‌دیم. 🚀"
    )


def _zero_referral_nudge_text(campaign, source: str) -> str:
    if source == "referral":
        return (
            "👋 <b>تو با دعوت یک دوست وارد مسابقه شدی؛ حالا نوبت لینک خودته.</b>\n\n"
            "هنوز کسی لینک اختصاصی خودت رو باز نکرده.\n"
            f"🎯 با <b>{campaign.invites_per_point}</b> دعوت فعال اولین امتیاز موقتت ساخته می‌شه.\n"
            "این آخرین یادآوری خودکار ما برای شروع دعوتته؛ لینک رو برای ۲ نفر که فکر می‌کنی مسابقه براشون جذابه بفرست 👇"
        )
    return (
        "🔥 <b>هنوز اولین دعوتت ثبت نشده.</b>\n\n"
        f"🎯 با <b>{campaign.invites_per_point}</b> دعوت فعال اولین امتیاز موقتت ساخته می‌شه.\n"
        "اگر هنوز می‌خوای شرکت کنی، این آخرین یادآوری خودکار ما برای شروع دعوتته؛ "
        "لینکت رو برای چند نفر بفرست 👇"
    )


def _engagement_v2_candidates(
    db: ReferralDB,
    campaign_id: int,
    cohort_cutoff: str,
    limit: int = 100,
) -> list[dict]:
    """One-time reactivation cohort: existing link holders with zero downstream activity."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT l.user_id,l.invite_link,l.created_at
               FROM invite_links l
               WHERE l.campaign_id=? AND l.created_at<=?
                 AND EXISTS (
                   SELECT 1 FROM funnel_events e
                   WHERE e.campaign_id=l.campaign_id
                     AND e.user_id=l.user_id
                     AND e.event_type='entered_contest'
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM funnel_events e
                   WHERE e.campaign_id=l.campaign_id
                     AND e.user_id=l.user_id
                     AND e.event_type='referral_open_received'
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM pending_referrals p
                   WHERE p.campaign_id=l.campaign_id
                     AND p.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM referrals r
                   WHERE r.campaign_id=l.campaign_id
                     AND r.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM funnel_events sent
                   WHERE sent.campaign_id=l.campaign_id
                     AND sent.user_id=l.user_id
                     AND sent.event_type='nudge_engagement_v2_sent'
                 )
               ORDER BY l.created_at ASC
               LIMIT ?""",
            (campaign_id, cohort_cutoff, max(1, limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def _engagement_v2_keyboard(link: str, campaign) -> InlineKeyboardMarkup:
    share_text = (
        f"من تو مسابقه {campaign.name} «الان چنده؟» شرکت کردم 🎁\n"
        f"{campaign.prize_text} جایزه و {campaign.num_winners} برنده داره.\n"
        "اگه دوست داشتی تو هم از لینک من وارد شو 👇"
    )
    share_url = "https://t.me/share/url?" + urlencode({
        "url": link,
        "text": share_text,
    })
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال برای ۲ نفر", url=share_url)],
        [InlineKeyboardButton("📊 وضعیت من", callback_data="menu:stats")],
    ])


def _qualification_soon_candidates(
    db: ReferralDB,
    campaign,
    now,
    within_hours: int = 24,
    limit: int = 100,
) -> list[dict]:
    """Active referrals that will qualify soon and have not produced a heads-up yet."""
    if campaign.min_stay_hours <= 0:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT r.id,r.referrer_id,r.joined_user_id,r.joined_first_name,r.stay_since
               FROM referrals r
               WHERE r.campaign_id=? AND r.active=1
                 AND NOT EXISTS (
                   SELECT 1 FROM funnel_events f
                   WHERE f.campaign_id=r.campaign_id
                     AND f.user_id=r.referrer_id
                     AND f.event_type='nudge_qualification_soon_sent'
                     AND f.source=('referral:' || r.joined_user_id)
                 )
               ORDER BY r.stay_since ASC
               LIMIT ?""",
            (campaign.id, max(1, limit * 3)),
        ).fetchall()

    horizon = within_hours * 3600
    result = []
    for row in rows:
        qualifies_at = parse_datetime(row["stay_since"]) + timedelta(
            hours=campaign.min_stay_hours
        )
        remaining = int((qualifies_at - now).total_seconds())
        if 0 < remaining <= horizon:
            item = dict(row)
            item["remaining_seconds"] = remaining
            result.append(item)
            if len(result) >= limit:
                break
    return result


async def _bot_username(application: Application) -> str:
    username = application.bot.username
    if username:
        return username
    me = await application.bot.get_me()
    if not me.username:
        raise RuntimeError("bot username is unavailable")
    return me.username


def _deep_link(username: str, payload: str) -> str:
    payload = str(payload or "").strip()
    if payload.startswith("https://t.me/") or payload.startswith("http://t.me/"):
        return payload
    return f"https://t.me/{username}?start={payload}"


async def nudge_pass(application: Application) -> dict:
    settings: Settings = application.bot_data["settings"]
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {
            "campaign": None,
            "early_share": 0,
            "zero_referral": 0,
            "qualification_soon": 0,
            "engagement_v2": 0,
            "promo_abandon": 0,
            "summaries": 0,
        }

    username = await _bot_username(application)

    early_rows = _early_share_nudge_candidates(
        db,
        campaign.id,
        utcnow() - timedelta(hours=settings.early_share_nudge_hours),
        limit=100,
    )
    early_sent = 0
    for row in early_rows:
        uid = int(row["user_id"])
        if not _notification_allowed(application, campaign.id, uid):
            continue
        source = _participant_first_touch_source(db, campaign.id, uid)
        try:
            deep_link = _deep_link(username, row.get("invite_link", ""))
            await application.bot.send_message(
                uid,
                _early_share_nudge_text(campaign, source),
                parse_mode=ParseMode.HTML,
                reply_markup=link_keyboard(settings, deep_link, campaign),
            )
            early_sent += 1
            db.track_funnel_event(campaign.id, uid, "nudge_early_share_sent", source)
        except (Forbidden, BadRequest):
            db.track_funnel_event(campaign.id, uid, "nudge_early_share_sent", "unreachable")
        except TelegramError:
            log.exception("Early-share nudge failed user=%s", uid)

    zero_rows = db.zero_referral_nudge_candidates(
        campaign.id,
        utcnow() - timedelta(hours=settings.zero_referral_nudge_hours),
        limit=100,
    )
    zero_sent = 0
    for row in zero_rows:
        uid = int(row["user_id"])
        source = _participant_first_touch_source(db, campaign.id, uid)
        try:
            deep_link = _deep_link(username, row.get("invite_link", ""))
            await application.bot.send_message(
                uid,
                _zero_referral_nudge_text(campaign, source),
                parse_mode=ParseMode.HTML,
                reply_markup=link_keyboard(settings, deep_link, campaign),
            )
            zero_sent += 1
            db.track_funnel_event(campaign.id, uid, "nudge_zero_referral_sent", source)
        except (Forbidden, BadRequest):
            db.track_funnel_event(campaign.id, uid, "nudge_zero_referral_sent", "unreachable")
        except TelegramError:
            log.exception("Zero-referral nudge failed user=%s", uid)

    engagement_v2_sent = 0
    # One-time reactivation experiment for the paeez1405 participants who
    # already had links before the 2026-09-19 measurement snapshot but had
    # produced no observable referral activity. Future participants are not
    # enrolled in this cohort.
    if campaign.slug == "paeez1405":
        v2_rows = _engagement_v2_candidates(
            db,
            campaign.id,
            "2026-09-19T16:18:00+00:00",
            limit=100,
        )
        for row in v2_rows:
            uid = int(row["user_id"])
            if not _notification_allowed(application, campaign.id, uid):
                continue
            deep_link = _deep_link(username, row.get("invite_link", ""))
            try:
                await application.bot.send_message(
                    uid,
                    "🎯 <b>هنوز کسی لینک دعوتت رو باز نکرده.</b>\n\n"
                    f"برای اولین امتیاز موقت فقط <b>{campaign.invites_per_point} دعوت فعال</b> لازم داری.\n\n"
                    "لازم نیست لینک رو همه‌جا بفرستی؛ همین الان فقط برای ۲ نفر "
                    "که فکر می‌کنی مسابقه براشون جذابه بفرست.\n\n"
                    "👀 وقتی اولین نفر لینک رو باز کنه، همینجا بهت خبر می‌دیم.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_engagement_v2_keyboard(deep_link, campaign),
                    disable_web_page_preview=True,
                )
                engagement_v2_sent += 1
                db.track_funnel_event(
                    campaign.id,
                    uid,
                    "nudge_engagement_v2_sent",
                    "cohort_20260919",
                )
            except (Forbidden, BadRequest):
                db.track_funnel_event(
                    campaign.id,
                    uid,
                    "nudge_engagement_v2_sent",
                    "unreachable",
                )
            except TelegramError:
                log.exception("Engagement-v2 nudge failed user=%s", uid)

    soon_rows = _qualification_soon_candidates(db, campaign, utcnow(), within_hours=24, limit=100)
    by_referrer: dict[int, list[dict]] = {}
    for row in soon_rows:
        by_referrer.setdefault(int(row["referrer_id"]), []).append(row)

    qualification_soon_sent = 0
    for referrer_id, rows in by_referrer.items():
        if not _notification_allowed(application, campaign.id, referrer_id):
            continue
        nearest = min(int(row["remaining_seconds"]) for row in rows)
        count = len(rows)
        subject = "یکی از دعوت‌هات" if count == 1 else f"{count} تا از دعوت‌هات"
        try:
            await application.bot.send_message(
                referrer_id,
                f"⏳ <b>{subject} به تأیید نزدیک شده.</b>\n\n"
                f"نزدیک‌ترین تأیید: <b>{remaining_label(nearest)}</b> دیگر\n"
                "اگر تا آن زمان در کانال بماند، در بلیت‌های تأییدشده قرعه‌کشی حساب می‌شود.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📊 دیدن وضعیت من", callback_data="menu:stats")
                ]]),
            )
            qualification_soon_sent += 1
            for row in rows:
                db.track_funnel_event(
                    campaign.id,
                    referrer_id,
                    "nudge_qualification_soon_sent",
                    f"referral:{int(row['joined_user_id'])}",
                )
        except (Forbidden, BadRequest):
            pass
        except TelegramError:
            log.exception("Qualification-soon nudge failed referrer=%s", referrer_id)

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
        "early_share": early_sent,
        "zero_referral": zero_sent,
        "qualification_soon": qualification_soon_sent,
        "engagement_v2": engagement_v2_sent,
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
