from __future__ import annotations

import logging
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from .config import hours_label, telegram_membership
from .context import services
from .ui import link_keyboard, main_keyboard
from .user_handlers import finalize_pending_referral, get_or_create_link

log = logging.getLogger("alanchande_referral_bot")


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
            "هنوز عضو کانال نیستی. داخل کانال روی Join Channel / عضویت بزن و بعد برگرد.",
            show_alert=True,
        )
        return

    result = await finalize_pending_referral(context, campaign, user)
    if result == "missing":
        await query.answer("دعوت در انتظار برای این حساب پیدا نشد.", show_alert=True)
        return

    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    await query.answer("عضویت تأیید شد ✅")

    try:
        await query.edit_message_text(
            "✅ <b>عضویتت تأیید شد و دعوت ثبت شد.</b>\n\n"
            f"اگر <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته در کانال بمانی، "
            "دعوت تأیید نهایی می‌شود.",
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise

    first_name = escape(user.first_name or "دوست عزیز")
    await context.bot.send_message(
        chat_id=user.id,
        text=(
            f"🎉 <b>{first_name}، تبریک!</b>\n\n"
            "حالا خودت هم عضو مسابقه‌ای و می‌تونی با دعوت دوستات شانس برنده شدنت رو بیشتر کنی.\n\n"
            f"🎟 هر <b>{campaign.invites_per_point}</b> دعوت تأییدشده = <b>۱ امتیاز</b>\n"
            "👇 از منوی زیر می‌تونی لینک دعوتت، امتیازها، دعوت‌ها، جدول مسابقه و جوایز رو ببینی."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings),
        disable_web_page_preview=True,
    )

    try:
        link = await get_or_create_link(context, campaign, user)
    except Exception:
        log.exception("Could not create referral link for newly onboarded participant %s", user.id)
        return

    await context.bot.send_message(
        chat_id=user.id,
        text=(
            f"<b>🔗 لینک اختصاصی دعوت تو:</b>\n\n{link}\n\n"
            "همین لینک رو برای دوستات بفرست؛ هر دعوت تأییدشده شانس تو رو برای برنده شدن بیشتر می‌کنه. 🚀"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=link_keyboard(settings, link),
        disable_web_page_preview=True,
    )
