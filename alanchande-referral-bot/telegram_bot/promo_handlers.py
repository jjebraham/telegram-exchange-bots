from __future__ import annotations

import asyncio
import logging
import re
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from .config import telegram_membership
from .context import services
from .ui import (
    campaign_end_text,
    link_keyboard,
    main_keyboard,
    menu_text,
    no_campaign_text,
)
from .user_handlers import cmd_start as legacy_cmd_start, get_or_create_link

log = logging.getLogger("alanchande_referral_bot")
_SOURCE_RE = re.compile(r"[^a-z0-9_-]+")


def _source_from_payload(payload: str) -> str:
    if payload.startswith("promo_"):
        source = payload[len("promo_"):]
        source = _SOURCE_RE.sub("_", source.lower()).strip("_")
        return source[:64] or "promo"
    return "organic"


def _entry_keyboard(channel_url: str, campaign_id: int, is_member: bool) -> InlineKeyboardMarkup:
    rows = []
    if not is_member:
        rows.append([InlineKeyboardButton("1️⃣ ورود به کانال و عضویت", url=channel_url)])
        label = "✅ عضو شدم؛ شروع مسابقه"
    else:
        label = "🚀 شروع مسابقه و دریافت لینک"
    rows.append([InlineKeyboardButton(label, callback_data=f"promo:enter:{campaign_id}")])
    return InlineKeyboardMarkup(rows)


def _entry_text(campaign, is_member: bool) -> str:
    if is_member:
        steps = "عضو کانال هستی ✅ فقط روی دکمه زیر بزن تا لینک اختصاصی‌ات ساخته شود."
    else:
        steps = (
            "1️⃣ وارد کانال شو و روی دکمه عضویت بزن.\n"
            "2️⃣ بعد به <b>همین چت</b> برگرد.\n"
            "3️⃣ روی «✅ عضو شدم؛ شروع مسابقه» بزن."
        )
    prize = escape(campaign.prize_text) if campaign.prize_text else "جوایز نقدی مسابقه"
    return (
        f"🎁 <b>{escape(campaign.name)}</b>\n\n"
        f"💰 <b>جوایز:</b> {prize}\n"
        f"🏆 <b>{campaign.num_winners} برنده</b>\n"
        f"⏰ پایان ثبت دعوت: <b>{campaign_end_text(campaign)}</b>\n\n"
        f"{steps}\n\n"
        "بعد از ورود، لینک اختصاصی خودت را می‌گیری و می‌توانی همان لحظه برای دوستانت بفرستی. 🚀"
    )


async def _membership_with_retry(context: ContextTypes.DEFAULT_TYPE, settings, user_id: int) -> bool:
    """Telegram membership propagation can lag briefly after Join."""
    last_error = None
    for delay in (0, 2, 5):
        if delay:
            await asyncio.sleep(delay)
        try:
            if await telegram_membership(context.bot, settings, user_id):
                return True
        except TelegramError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return False


async def cmd_start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Low-friction /start flow for promotional traffic."""
    settings, db = services(context)
    user = update.effective_user
    if not user or not update.message:
        return
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)

    payload = context.args[0].strip() if context.args else ""

    if payload.startswith("ref_"):
        owner = db.invite_owner(payload)
        if owner:
            campaign, _ = owner
            db.track_funnel_event(campaign.id, user.id, "bot_start", "referral")
            db.track_funnel_event(campaign.id, user.id, "referral_open", "referral")
        await legacy_cmd_start(update, context)
        return

    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text(no_campaign_text())
        return

    source = _source_from_payload(payload)
    db.track_funnel_event(campaign.id, user.id, "bot_start", source)

    if db.get_invite_link(campaign.id, user.id):
        await legacy_cmd_start(update, context)
        return

    try:
        is_member = await telegram_membership(context.bot, settings, user.id)
    except TelegramError:
        log.exception("Could not check contest-entry membership for %s", user.id)
        await update.message.reply_text(
            "فعلاً نتونستم عضویتت رو بررسی کنم. چند لحظه دیگه دوباره امتحان کن."
        )
        return

    await update.message.reply_text(
        _entry_text(campaign, is_member),
        parse_mode=ParseMode.HTML,
        reply_markup=_entry_keyboard(settings.channel_url, campaign.id, is_member),
    )


async def on_promo_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    settings, db = services(context)
    data = query.data or ""
    try:
        campaign_id = int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("درخواست نامعتبر است.", show_alert=True)
        return

    campaign = db.live_campaign()
    if not campaign or campaign.id != campaign_id:
        await query.answer("این مسابقه در حال حاضر فعال نیست.", show_alert=True)
        return

    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    try:
        is_member = await _membership_with_retry(context, settings, user.id)
    except TelegramError:
        log.exception("Could not verify contest-entry membership for %s", user.id)
        await query.answer("بررسی عضویت ممکن نشد. چند لحظه بعد دوباره امتحان کن.", show_alert=True)
        return

    if not is_member:
        await query.answer(
            "هنوز عضویتت رو نمی‌بینم 🤔 اول دکمه 1️⃣ رو بزن، داخل کانال عضو شو و بعد به همین چت برگرد.",
            show_alert=True,
        )
        return

    try:
        link = await get_or_create_link(context, campaign, user)
    except Exception:
        log.exception("Could not create promotional participant link for %s", user.id)
        await query.answer("ساخت لینک با خطا روبه‌رو شد. دوباره امتحان کن.", show_alert=True)
        return

    db.track_funnel_event(campaign.id, user.id, "entered_contest", "")
    db.track_funnel_event(campaign.id, user.id, "link_created", "")

    await query.answer("لینک اختصاصی‌ات آماده شد 🚀")
    success_text = (
        "🎉 <b>عالیه! وارد مسابقه شدی.</b>\n\n"
        "لینک اختصاصی‌ات آماده است؛ همین حالا برای دوستات بفرست 👇\n\n"
        f"<b>🔗 لینک تو:</b>\n{link}\n\n"
        f"⭐ هر {campaign.invites_per_point} دعوت فعال = ۱ امتیاز موقت\n"
        "🎟 بعد از کامل‌شدن دوره عضویت، بلیت قرعه‌کشی تأیید می‌شود."
    )
    try:
        await query.edit_message_text(
            success_text,
            parse_mode=ParseMode.HTML,
            reply_markup=link_keyboard(settings, link, campaign),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise

    await context.bot.send_message(
        user.id,
        menu_text(campaign, user.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings),
        disable_web_page_preview=True,
    )
