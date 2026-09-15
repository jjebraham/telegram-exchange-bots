from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from .config import telegram_membership
from .context import services
from .ui import link_keyboard, main_keyboard, menu_text, no_campaign_text
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
        rows.append([InlineKeyboardButton("📢 اول عضو کانال شو", url=channel_url)])
        label = "✅ عضو شدم؛ شروع مسابقه"
    else:
        label = "🚀 شروع مسابقه و دریافت لینک"
    rows.append([InlineKeyboardButton(label, callback_data=f"promo:enter:{campaign_id}")])
    return InlineKeyboardMarkup(rows)


def _entry_text(campaign, is_member: bool) -> str:
    first_step = (
        "عضو کانال هستی؛ فقط روی دکمه زیر بزن تا لینک اختصاصی دعوتت ساخته بشه."
        if is_member
        else "اول عضو کانال شو، بعد برگرد و روی «عضو شدم؛ شروع مسابقه» بزن."
    )
    return (
        f"🎁 <b>{campaign.name}</b>\n\n"
        "برای شرکت در قرعه‌کشی آماده‌ای؟ 🔥\n\n"
        f"{first_step}\n\n"
        f"✅ هر <b>{campaign.invites_per_point} دعوت فعال</b> = <b>۱ امتیاز فعلی</b>\n"
        f"🏆 <b>{campaign.num_winners} برنده</b> در پایان مسابقه\n\n"
        "هرچه امتیازت بیشتر باشه، شانس برنده شدنت بیشتره."
    )


async def cmd_start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Low-friction /start flow for promotional traffic.

    Referral deep links keep their existing attribution flow. Existing participants
    keep the normal menu. New participants see a single contest-start CTA.
    """
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

    # Existing participants should continue to get their normal menu/link immediately.
    if db.get_invite_link(campaign.id, user.id):
        await legacy_cmd_start(update, context)
        return

    try:
        is_member = await telegram_membership(context.bot, settings, user.id)
    except TelegramError:
        log.exception("Could not check contest-entry membership for %s", user.id)
        await update.message.reply_text(
            "فعلاً نتونستم عضویتت رو بررسی کنم. چند لحظه دیگه دوباره /start رو بزن."
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
        is_member = await telegram_membership(context.bot, settings, user.id)
    except TelegramError:
        log.exception("Could not verify contest-entry membership for %s", user.id)
        await query.answer("بررسی عضویت ممکن نشد. چند لحظه بعد دوباره امتحان کن.", show_alert=True)
        return

    if not is_member:
        await query.answer(
            "هنوز عضو کانال نیستی. اول داخل کانال روی Join Channel / عضویت بزن.",
            show_alert=True,
        )
        return

    try:
        link = await get_or_create_link(context, campaign, user)
    except Exception:
        log.exception("Could not create promotional participant link for %s", user.id)
        await query.answer("ساخت لینک با خطا روبه‌رو شد. دوباره امتحان کن.", show_alert=True)
        return

    await query.answer("لینک اختصاصی‌ات آماده شد 🚀")
    try:
        await query.edit_message_text(
            "🎉 <b>عالیه! وارد مسابقه شدی.</b>\n\n"
            "لینک اختصاصی‌ات آماده است. برای دوستات بفرست و امتیاز جمع کن 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(settings),
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise

    await context.bot.send_message(
        user.id,
        f"<b>🔗 لینک اختصاصی تو:</b>\n\n{link}\n\n"
        "این لینک رو برای دوستات بفرست؛ ربات مرحله‌به‌مرحله عضویت رو بهشون توضیح می‌ده.",
        parse_mode=ParseMode.HTML,
        reply_markup=link_keyboard(settings, link),
        disable_web_page_preview=True,
    )

    # Follow with the main contest summary so the participant immediately sees all options.
    await context.bot.send_message(
        user.id,
        menu_text(campaign, user.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings),
        disable_web_page_preview=True,
    )
