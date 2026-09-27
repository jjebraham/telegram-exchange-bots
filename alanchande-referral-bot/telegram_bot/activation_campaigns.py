"""Admin-triggered, previewed one-time activation campaigns. Never sent on startup."""

import asyncio
import logging
import secrets
import time
from datetime import datetime, timedelta
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from referral_core import utcnow
from .activation_store import (
    SEGMENTS, activity_snapshot, activation_report, claim_recipient, eligibility,
    eligible_recipients, finish_recipient, finish_run, get_run, pending_recipients,
    refresh_attempt, start_run,
)
from .config import hours_label
from .context import is_admin, services
from .publish import _bot_username
from .reporting import reply_report
from .ui import _fa_number, invitation_share_url

log = logging.getLogger("alanchande_referral_bot")
PREVIEW_TTL = 15 * 60


def activation_message(campaign, counts, segment):
    """Return personalized copy and the primary action (share or waiting status)."""
    title = escape(campaign.name)
    stay = hours_label(campaign.min_stay_hours)
    if segment == "first_friend":
        return (
            f"🎁 <b>دعوت اولت در مسابقه {title}</b>\n\n"
            "لینک اختصاصی‌ات آماده است؛ اولین قدم، دعوت از <b>یک دوست</b> است.\n"
            f"هر <b>{_fa_number(campaign.invites_per_point)} دعوت فعال</b> یک امتیاز موقت می‌سازد؛ "
            f"دعوت‌هایی که <b>{stay}</b> پیوسته عضو بمانند و به‌موقع وارد شوند، "
            "برای بلیت تأییدشده حساب می‌شوند.\n\n"
            "👇 لینک خودت را برای یک دوست بفرست.", "📤 دعوت اولین دوست", False,
        )
    if segment != "next_ticket":
        raise ValueError("Unknown activation segment")
    threshold = campaign.invites_per_point
    committed = counts["qualified"] % threshold + counts["qualifiable_pending"]
    if committed >= threshold:
        return (
            f"🎟 <b>وضعیت بلیت بعدی — {title}</b>\n\n"
            f"الان <b>{_fa_number(counts['confirmed_points'])}</b> بلیت تأییدشده داری.\n"
            "⏳ برای بلیت بعدی، دعوت فعال کافی در دوره ماندگاری داری. "
            f"اگر عضویت آن‌ها تا تکمیل <b>{stay}</b> پیوسته ادامه پیدا کند، "
            "بلیت بعدی تأیید می‌شود.\n\n"
            "وضعیت دعوت‌ها و زمان باقی‌مانده را ببین 👇", "📊 وضعیت بلیت بعدی", True,
        )
    needed = threshold - committed
    pending_line = (
        f"⏳ <b>{_fa_number(counts['qualifiable_pending'])}</b> دعوت فعال در انتظار تأیید داری.\n"
        if counts["qualifiable_pending"] else ""
    )
    return (
        f"🎟 <b>بلیت بعدی تو — {title}</b>\n\n"
        f"الان <b>{_fa_number(counts['confirmed_points'])}</b> بلیت تأییدشده داری.\n"
        f"{pending_line}"
        f"با <b>{_fa_number(needed)} دعوت فعال دیگر</b> مسیر بلیت دوم کامل می‌شود. "
        f"دعوت‌های در انتظار باید <b>{stay}</b> پیوسته عضو بمانند و به‌موقع وارد شوند "
        "تا بلیت تأیید شود.\n\n"
        "بلیت‌های بیشتر سهمت را در قرعه‌کشی وزن‌دار بیشتر می‌کنند؛ برد تضمین نمی‌شود.\n"
        "👇 لینک آماده‌ات را برای دوستانت بفرست.",
        f"📤 دعوت {_fa_number(needed)} دوست دیگر", False,
    )


def activation_keyboard(link, label, waiting=False):
    primary = (
        InlineKeyboardButton(label, callback_data="menu:stats") if waiting else
        InlineKeyboardButton(label, url=invitation_share_url(link))
    )
    return InlineKeyboardMarkup([
        [primary],
        [InlineKeyboardButton("📊 وضعیت من", callback_data="menu:stats")]
        if not waiting else [InlineKeyboardButton("⬅️ منوی مسابقه", callback_data="menu:main")],
    ])


def report_text(db, campaign):
    lines = [f"📣 Activation results — {campaign.slug}", ""]
    for segment in SEGMENTS:
        report = activation_report(db, campaign, segment)
        if not report:
            lines.append(f"• {segment}: not launched")
            continue
        states = report["states"]
        uncertain = states.get("unknown", 0) + states.get("sending", 0)
        lines.extend([
            f"• {segment} — started {report['run']['started_at']}",
            f"  frozen audience={report['eligible']} delivered={states.get('sent', 0)} "
            f"pending={states.get('pending', 0)} skipped={states.get('skipped', 0)} "
            f"failed={states.get('failed', 0)} uncertain={uncertain}",
            f"  recipients with new opens={report['with_new_open']} (new referrer/candidate pairs={report['new_opens']})",
            f"  recipients with new joins={report['with_new_join']} (new joined referrals={report['new_joins']})",
            f"  recipients with more confirmed tickets now={report['with_more_tickets_now']}",
        ])
    lines.extend([
        "", "Opens/joins start at each recipient's delivery time; previously known candidates are excluded.",
        "Ticket gains can include maturation of existing referrals. These are observational results, not proof of causal uplift.",
        "Native share completion is unavailable. Uncertain deliveries are never automatically resent.",
    ])
    return "\n".join(lines)


async def cmd_activation_report(update, context):
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /activation_report [campaign_slug] — campaign not found.")
        return
    await reply_report(update.message, report_text(db, campaign))


async def cmd_activation_preview(update, context):
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("این دستور را در چت خصوصی با ربات اجرا کن.")
        return
    if len(context.args or []) != 1 or context.args[0] not in SEGMENTS:
        await update.message.reply_text("Usage: /activation_preview next_ticket | first_friend")
        return
    segment = context.args[0]
    campaign = db.live_campaign()
    if not campaign or utcnow() >= campaign.final_qualification_cutoff:
        await update.message.reply_text("مسابقه فعال با فرصت کافی برای تأیید دعوت جدید وجود ندارد.")
        return
    run = get_run(db, campaign.id, segment)
    # A resumed preview uses only the original audience; no new users can enter.
    if run:
        rows = []
        for uid in pending_recipients(db, campaign.id, segment):
            recipient, _ = eligibility(db, campaign, uid, segment)
            if recipient:
                rows.append(recipient)
        if not rows:
            await reply_report(update.message, report_text(db, campaign))
            return
    else:
        rows = eligible_recipients(db, campaign, segment)
    if not rows:
        await update.message.reply_text("هیچ مخاطب واجد شرایطی نیست. یادآوری‌های ۲۴ ساعت اخیر و فعالیت قبلی لحاظ شده‌اند.")
        return
    try:
        username = await _bot_username(context)
    except Exception:
        log.exception("Could not resolve bot username for activation preview")
        await update.message.reply_text("نام کاربری ربات در دسترس نیست؛ دوباره تلاش کن.")
        return
    now = time.time()
    previews = context.application.bot_data.setdefault("activation_previews", {})
    for key in list(previews):
        if previews[key]["expires_at"] < now:
            previews.pop(key)
    token = secrets.token_urlsafe(8)
    previews[token] = {
        "admin_id": update.effective_user.id, "campaign_id": campaign.id,
        "segment": segment, "user_ids": [r["user_id"] for r in rows],
        "expires_at": now + PREVIEW_TTL,
    }
    await update.message.reply_text(
        f"🔎 پیش‌نمایش {segment}\nمخاطبان واجد شرایط: {len(rows)}\n"
        "پیام هر نفر بر اساس وضعیت فعلی‌اش شخصی‌سازی می‌شود. پیش‌نمایش ۱۵ دقیقه اعتبار دارد.\n"
        "هیچ پیامی تا زدن دکمه ارسال نمی‌شود. این ارسال برای هر مسابقه و گروه فقط یک بار است.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ارسال به این گروه", callback_data=f"activate:yes:{token}"),
            InlineKeyboardButton("❌ لغو", callback_data=f"activate:no:{token}"),
        ]]),
    )
    # Show each copy variant present in this audience, with one actual personal link.
    shown = set()
    for row in rows:
        text, label, waiting = activation_message(campaign, row["counts"], segment)
        if label in shown:
            continue
        shown.add(label)
        link = f"https://t.me/{username}?start={row['payload']}"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML,
            reply_markup=activation_keyboard(link, label, waiting), disable_web_page_preview=True)


async def send_activation_campaign(application, campaign_id, segment, username, admin_id):
    db = application.bot_data["db"]
    settings = application.bot_data["settings"]
    try:
        for uid in pending_recipients(db, campaign_id, segment):
            campaign = db.live_campaign()
            if not campaign or campaign.id != campaign_id:
                finish_recipient(db, campaign_id, segment, uid, "skipped", reason="campaign_changed")
                continue
            recipient, reason = eligibility(db, campaign, uid, segment)
            if not recipient:
                finish_recipient(db, campaign_id, segment, uid, "skipped", reason=reason)
                continue
            if not db.notification_gate(campaign_id, uid,
                    settings.notification_max_per_window, settings.notification_window_seconds):
                finish_recipient(db, campaign_id, segment, uid, "skipped", reason="notification_throttle")
                continue
            if not claim_recipient(db, campaign, segment, uid, activity_snapshot(db, campaign, uid)):
                continue
            for attempt in range(3):
                # Qualification, departures or the deadline can change during rate-limit waits.
                live = db.live_campaign()
                current, reason = eligibility(db, live, uid, segment) if live and live.id == campaign_id else (None, "campaign_changed")
                if not current:
                    finish_recipient(db, campaign_id, segment, uid, "skipped", reason=reason)
                    break
                text, label, waiting = activation_message(live, current["counts"], segment)
                link = f"https://t.me/{username}?start={current['payload']}"
                attempted_at = utcnow()
                refresh_attempt(db, live, segment, uid,
                                activity_snapshot(db, live, uid, attempted_at), attempted_at)
                try:
                    sent = await application.bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                        reply_markup=activation_keyboard(link, label, waiting), disable_web_page_preview=True)
                except RetryAfter as exc:
                    if attempt == 2:
                        finish_recipient(db, campaign_id, segment, uid, "failed", reason="rate_limited")
                        break
                    delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, timedelta) else float(exc.retry_after)
                    await asyncio.sleep(max(0, delay) + 0.25)
                    continue
                except (Forbidden, BadRequest) as exc:
                    finish_recipient(db, campaign_id, segment, uid, "failed", reason=type(exc).__name__)
                except TelegramError as exc:
                    # The server may have delivered a timed-out request. Do not retry it.
                    finish_recipient(db, campaign_id, segment, uid, "unknown", reason=type(exc).__name__)
                else:
                    delivered_at = getattr(sent, "date", None)
                    if not isinstance(delivered_at, datetime):
                        delivered_at = utcnow()
                    delivered_at = max(attempted_at, delivered_at)
                    finish_recipient(db, campaign_id, segment, uid, "sent",
                                     message_id=sent.message_id, now=delivered_at)
                    db.track_funnel_event(campaign_id, uid, "activation_campaign_sent", segment)
                break
            await asyncio.sleep(0.1)
        finish_run(db, campaign_id, segment)
        with db.connect() as conn:
            row = conn.execute("SELECT slug FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        campaign = db.get_campaign(row["slug"]) if row else None
        if campaign:
            await application.bot.send_message(admin_id, report_text(db, campaign), parse_mode=None)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Activation campaign interrupted: campaign=%s segment=%s", campaign_id, segment)
    finally:
        application.bot_data.setdefault("activation_tasks", {}).pop((campaign_id, segment), None)


async def on_activation_callback(update, context):
    settings, db = services(context)
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if not is_admin(update, settings) or not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        await query.answer("اجازه این کار را نداری.", show_alert=True)
        return
    parts = (query.data or "").split(":")
    previews = context.application.bot_data.setdefault("activation_previews", {})
    preview = previews.get(parts[2]) if len(parts) == 3 and parts[0] == "activate" else None
    if not preview or time.time() > preview["expires_at"]:
        await query.answer("پیش‌نمایش منقضی شده؛ دوباره /activation_preview را اجرا کن.", show_alert=True)
        return
    if preview["admin_id"] != update.effective_user.id:
        await query.answer("فقط سازنده پیش‌نمایش می‌تواند ارسال را تأیید کند.", show_alert=True)
        return
    if parts[1] == "no":
        previews.pop(parts[2])
        await query.answer("لغو شد.")
        await query.edit_message_reply_markup(reply_markup=None)
        return
    if parts[1] != "yes":
        await query.answer("درخواست نامعتبر است.", show_alert=True)
        return
    campaign = db.live_campaign()
    if not campaign or campaign.id != preview["campaign_id"] or utcnow() >= campaign.final_qualification_cutoff:
        await query.answer("مسابقه یا مهلت دعوت تغییر کرده؛ پیش‌نمایش جدید بساز.", show_alert=True)
        return
    segment = preview["segment"]
    tasks = context.application.bot_data.setdefault("activation_tasks", {})
    key = (campaign.id, segment)
    if preview.get("busy") or key in tasks:
        await query.answer("این گروه در حال ارسال است.", show_alert=True)
        return
    preview["busy"] = True
    try:
        username = await _bot_username(context)
    except Exception:
        preview["busy"] = False
        await query.answer("نام کاربری ربات در دسترس نیست؛ دوباره تلاش کن.", show_alert=True)
        return
    # Another preview may have started this segment while username resolution awaited.
    if key in tasks:
        preview["busy"] = False
        await query.answer("این گروه در حال ارسال است.", show_alert=True)
        return
    start_run(db, campaign, segment, update.effective_user.id, preview["user_ids"])
    db.log_admin_action(campaign.id, update.effective_user.id, "activation_campaign_confirmed",
                        {"segment": segment, "preview_count": len(preview["user_ids"])})
    previews.pop(parts[2])
    # Reserve the task key before any further await; duplicate confirmations are harmless.
    tasks[key] = context.application.create_task(send_activation_campaign(
        context.application, campaign.id, segment, username, update.effective_user.id))
    await query.answer("ارسال شروع شد؛ گزارش نتیجه در همین چت می‌آید.")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass
