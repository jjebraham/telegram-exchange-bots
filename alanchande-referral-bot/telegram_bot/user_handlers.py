from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from referral_core import Campaign, ReferralDB
from .config import Settings, extract_status_change, hours_label, is_configured_channel, telegram_membership
from .context import services
from .ui import (
    back_keyboard, link_keyboard, main_keyboard, menu_text, no_campaign_text,
    render_prizes, render_referrals, render_rules, render_stats, render_top,
)

log = logging.getLogger("alanchande_referral_bot")
_link_locks: dict[tuple[int, int], asyncio.Lock] = {}


async def ensure_participant_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    settings, _ = services(context)
    try:
        return await telegram_membership(context.bot, settings, user_id)
    except TelegramError:
        log.exception("Could not verify participant membership for %s", user_id)
        return False


async def get_or_create_link(context: ContextTypes.DEFAULT_TYPE, campaign: Campaign, user) -> str:
    settings, db = services(context)
    existing = db.get_invite_link(campaign.id, user.id)
    if existing:
        return existing
    lock = _link_locks.setdefault((campaign.id, user.id), asyncio.Lock())
    async with lock:
        existing = db.get_invite_link(campaign.id, user.id)
        if existing:
            return existing
        invite = await context.bot.create_chat_invite_link(
            chat_id=settings.channel_ref,
            name=f"ref:{campaign.id}:{user.id}"[:32],
            expire_date=campaign.end_dt,
            creates_join_request=True,
        )
        return db.save_invite_link(campaign.id, user.id, invite.invite_link)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    user = update.effective_user
    if not user or not update.message:
        return
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text(no_campaign_text())
        return
    if not await ensure_participant_membership(context, user.id):
        await update.message.reply_text(
            "برای شرکت در مسابقه ابتدا باید عضو کانال باشی. بعد از عضویت دوباره /start را بزن. 👇",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 عضویت در کانال", url=settings.channel_url)]]),
        )
        return
    try:
        link = await get_or_create_link(context, campaign, user)
    except TelegramError:
        log.exception("Could not create invite link for %s", user.id)
        await update.message.reply_text("ساخت لینک اختصاصی با خطا روبه‌رو شد. لطفاً کمی بعد دوباره /start را بزن.")
        return
    await update.message.reply_text(
        menu_text(campaign, user.first_name), parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings), disable_web_page_preview=True,
    )
    await update.message.reply_text(
        f"<b>🔗 لینک اختصاصی تو:</b>\n\n{link}", parse_mode=ParseMode.HTML,
        reply_markup=link_keyboard(settings, link), disable_web_page_preview=True,
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    user = update.effective_user
    if not user or not update.message:
        return
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text(no_campaign_text())
        return
    await update.message.reply_text(
        menu_text(campaign, user.first_name), parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings), disable_web_page_preview=True,
    )


async def cmd_stats_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, db = services(context)
    campaign = db.live_campaign()
    if not campaign or not update.effective_user or not update.message:
        if update.message:
            await update.message.reply_text(no_campaign_text())
        return
    await update.message.reply_text(
        render_stats(campaign, db, update.effective_user.id),
        parse_mode=ParseMode.HTML, reply_markup=back_keyboard(),
    )


async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    settings, db = services(context)
    user = update.effective_user
    if not user:
        return
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    campaign = db.live_campaign()
    if not campaign:
        try:
            await query.edit_message_text(no_campaign_text())
        except BadRequest:
            pass
        return
    data = query.data or ""
    markup = back_keyboard()
    if data == "menu:main":
        text, markup = menu_text(campaign, user.first_name), main_keyboard(settings)
    elif data == "menu:stats":
        text = render_stats(campaign, db, user.id)
    elif data == "menu:referrals":
        text = render_referrals(campaign, db, user.id)
    elif data == "menu:top":
        text = render_top(campaign, db)
    elif data == "menu:rules":
        text = render_rules(campaign)
    elif data == "menu:prizes":
        text = render_prizes(campaign)
    elif data == "menu:link":
        if not await ensure_participant_membership(context, user.id):
            text = "برای دریافت لینک اختصاصی باید عضو کانال باشی."
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 عضویت در کانال", url=settings.channel_url)],
                [InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:main")],
            ])
        else:
            try:
                link = await get_or_create_link(context, campaign, user)
                text = f"<b>🔗 لینک اختصاصی تو</b>\n\n{link}\n\nاین لینک را برای دوستانت بفرست."
                markup = link_keyboard(settings, link)
            except TelegramError:
                log.exception("Could not create invite link")
                text = "ساخت لینک با خطا روبه‌رو شد. لطفاً دوباره تلاش کن."
    else:
        return
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def notify_referral_join(context: ContextTypes.DEFAULT_TYPE, campaign: Campaign, user,
                               referrer_id: int, result: str | None) -> None:
    if result not in {"created", "reactivated"}:
        return
    log.info(
        "Referral %s: joined=%s referrer=%s campaign=%s",
        result, user.id, referrer_id, campaign.slug,
    )
    try:
        await context.bot.send_message(
            referrer_id,
            f"🎉 یک نفر با لینک تو عضو شد!\n\n⏳ اگر <b>{hours_label(campaign.min_stay_hours)}</b> "
            f"پیوسته در کانال بماند، دعوت او تأیید می‌شود.",
            parse_mode=ParseMode.HTML,
        )
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify referrer %s", referrer_id)


async def on_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attribute referral links from join requests and approve them automatically.

    Public channels do not reliably include ChatMemberUpdated.invite_link on a
    membership transition. Referral links therefore use creates_join_request=True;
    ChatJoinRequest gives us the link before the user is approved.
    """
    settings, db = services(context)
    request = update.chat_join_request
    if request is None or not is_configured_channel(request.chat, settings):
        return

    user = request.from_user
    if getattr(user, "is_bot", False):
        return

    invite_link = request.invite_link.invite_link if request.invite_link else None
    if not invite_link:
        log.info("Ignoring unattributed join request from user=%s", user.id)
        return

    owner = db.invite_owner(invite_link)
    if not owner:
        log.info("Ignoring join request for unknown invite link from user=%s", user.id)
        return

    campaign, referrer_id = owner
    live = db.live_campaign()
    if not live or live.id != campaign.id:
        log.info(
            "Ignoring join request for non-live campaign=%s user=%s",
            campaign.slug, user.id,
        )
        return

    try:
        await context.bot.approve_chat_join_request(settings.channel_ref, user.id)
    except TelegramError:
        log.exception("Could not approve referral join request for user=%s", user.id)
        return

    result = db.record_join(
        campaign, user.id, referrer_id, user.username, user.first_name,
    )
    await notify_referral_join(context, campaign, user, referrer_id, result)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        invite_link = cmu.invite_link.invite_link if cmu.invite_link else None
        referrer_id = None
        result = None
        if invite_link:
            owner = db.invite_owner(invite_link)
            if owner and owner[0].id == campaign.id:
                _, referrer_id = owner
                result = db.record_join(campaign, user.id, referrer_id, user.username, user.first_name)
        else:
            referrer_id = db.reactivate_original(campaign.id, user.id, user.username, user.first_name)
            result = "reactivated" if referrer_id is not None else None
        if referrer_id is not None:
            await notify_referral_join(context, campaign, user, referrer_id, result)
    elif was_member and not is_member_now:
        changed = db.mark_left(user.id)
        if changed:
            log.info("Referral member left: user=%s records=%s", user.id, changed)


async def qualification_pass(application: Application) -> None:
    db: ReferralDB = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return
    for row in db.unnotified_qualified(campaign, limit=100):
        name = escape(row["joined_first_name"] or "دوستت")
        try:
            counts = db.campaign_counts(campaign, row["referrer_id"])
            await application.bot.send_message(
                row["referrer_id"],
                f"✅ دعوت <b>{name}</b> تأیید شد!\n\n👥 دعوت‌های تأییدشده: <b>{counts['qualified']}</b>\n"
                f"🎟 امتیاز فعلی: <b>{counts['points']}</b>",
                parse_mode=ParseMode.HTML,
            )
            db.mark_qualification_notified(row["id"])
        except (Forbidden, BadRequest):
            db.mark_qualification_notified(row["id"])
        except TelegramError:
            log.exception("Qualification notification failed for referral %s", row["id"])


async def qualification_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    while True:
        try:
            await qualification_pass(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Qualification worker failed")
        await asyncio.sleep(settings.qualification_check_seconds)


async def post_init(application: Application) -> None:
    application.bot_data["qualification_task"] = asyncio.create_task(
        qualification_loop(application), name="qualification-loop"
    )


async def post_stop(application: Application) -> None:
    task = application.bot_data.get("qualification_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
