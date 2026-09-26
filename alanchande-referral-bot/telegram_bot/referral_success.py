from __future__ import annotations

import logging
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from .config import hours_label, telegram_membership
from .context import services
from .ui import final_join_cutoff_text, referral_activation_keyboard
from .user_handlers import finalize_pending_referral, get_or_create_link

log = logging.getLogger("alanchande_referral_bot")


async def send_participant_welcome(context: ContextTypes.DEFAULT_TYPE, campaign, user) -> bool:
    """Welcome a confirmed invitee exactly once per campaign and expose their own referral link."""
    settings, db = services(context)
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)

    if db.participant_welcome_sent(campaign.id, user.id):
        return True

    try:
        link = await get_or_create_link(context, campaign, user)
    except Exception:
        db.track_funnel_event(
            campaign.id,
            user.id,
            "referral_link_creation_error",
            "referral",
        )
        log.exception("Could not create referral link for newly onboarded participant %s", user.id)
        return False

    first_name = escape(user.first_name or "دوست عزیز")
    if campaign.invites_per_point == 2:
        progress_line = (
            "🎯 <b>پیشرفت اولین امتیاز:</b>\n"
            "░░░░░░░░░░ <b>۰/۲</b>\n"
            "اگر همین یک نفر عضو شود: <b>۱/۲</b> ✅"
        )
    else:
        progress_line = (
            f"🎯 برای اولین امتیاز به <b>{campaign.invites_per_point}</b> دعوت فعال نیاز داری."
        )

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎉 <b>{first_name}، عضویتت تأیید شد!</b>\n\n"
                "از این لحظه خودت هم یک <b>شرکت‌کننده مستقل</b> مسابقه‌ای.\n"
                "دعوتی که بابت ورود تو برای دوستت ثبت شد جداست؛ "
                "<b>امتیازها و شانس برنده‌شدن تو برای خودته.</b> ✅\n\n"
                "🎯 <b>فقط یک کار مونده</b>\n\n"
                "لینکت آماده‌ست.\n"
                "<b>همین الان برای فقط ۱ نفر بفرست 👇</b>\n\n"
                f"{progress_line}\n\n"
                f"<b>🔗 لینک اختصاصی دعوت تو:</b>\n{link}\n\n"
                f"⭐ هر <b>{campaign.invites_per_point}</b> دعوت فعال = <b>۱ امتیاز موقت</b>\n"
                f"🎟 بعد از <b>{hours_label(campaign.min_stay_hours)}</b> ماندن پیوسته، "
                "آن دعوت تأیید می‌شود و در محاسبه بلیت‌های نهایی تو حساب می‌شود.\n\n"
                f"⏳ <b>آخرین زمان ورود دعوت جدید برای تأیید:</b> {final_join_cutoff_text(campaign)}"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=referral_activation_keyboard(settings, link, campaign),
            disable_web_page_preview=True,
        )
    except (Forbidden, BadRequest) as exc:
        db.track_funnel_event(
            campaign.id,
            user.id,
            "referral_welcome_error",
            "referral",
        )
        log.warning("Could not send participant welcome to user=%s: %s", user.id, exc)
        return False
    except TelegramError:
        db.track_funnel_event(
            campaign.id,
            user.id,
            "referral_welcome_error",
            "referral",
        )
        log.exception("Participant welcome failed for user=%s", user.id)
        return False

    db.track_funnel_event(campaign.id, user.id, "referral_welcome_sent", "referral")
    db.track_funnel_event(campaign.id, user.id, "referral_link_included", "referral")
    db.track_funnel_event(campaign.id, user.id, "referral_share_prompt_sent", "referral")
    db.track_funnel_event(campaign.id, user.id, "referral_share_prompt_v2_sent", "referral")
    db.track_funnel_event(campaign.id, user.id, "entered_contest", "referral")
    db.track_funnel_event(campaign.id, user.id, "link_created", "referral")
    db.mark_participant_welcome_sent(campaign.id, user.id)
    log.info("Participant welcome sent: user=%s campaign=%s", user.id, campaign.slug)
    return True


async def on_referral_check_and_welcome(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Verify membership, finalize the referral, then onboard the invitee as a participant."""
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
        await query.answer("این مسابقه دیگر فعال نیست.", show_alert=True)
        return

    try:
        is_member = await telegram_membership(context.bot, settings, user.id)
    except TelegramError:
        log.exception("Could not verify referral membership for user=%s", user.id)
        await query.answer(
            "بررسی عضویت فعلاً ممکن نیست. چند لحظه بعد دوباره بزن.",
            show_alert=True,
        )
        return

    if not is_member:
        await query.answer(
            "هنوز عضویتت رو نمی‌بینم 🤔 اول وارد کانال شو، روی Join Channel / عضویت بزن و بعد به همین چت برگرد.",
            show_alert=True,
        )
        return

    result = await finalize_pending_referral(context, campaign, user)
    if result == "missing":
        await query.answer("دعوت در انتظار برای این حساب پیدا نشد.", show_alert=True)
        return

    await query.answer("عضویت تأیید شد ✅")
    try:
        if result == "already_recorded":
            text = "✅ <b>عضویتت قبلاً تأیید شده و دعوت ثبت شده است.</b>"
        else:
            text = (
                "✅ <b>عضویتت تأیید شد و دعوت ثبت شد.</b>\n\n"
                "⭐ این دعوت از همین حالا در امتیاز موقت معرف حساب می‌شود.\n"
                f"🎟 اگر <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته در کانال بمانی، "
                "به بلیت تأییدشده قرعه‌کشی تبدیل می‌شود."
            )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise

    await send_participant_welcome(context, campaign, user)
