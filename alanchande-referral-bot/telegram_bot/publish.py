from __future__ import annotations

import logging
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from .context import is_admin, services
from .growth import build_promo_link, normalize_promo_source, promo_post_text

log = logging.getLogger("alanchande_referral_bot")
_PREVIEW_TTL_SECONDS = 15 * 60


def parse_publish_args(args: list[str]) -> tuple[str, str]:
    if not args:
        raise ValueError("Usage: /publish_promo <source> [a|b]")
    source = normalize_promo_source(args[0])
    variant = args[1].strip().lower() if len(args) > 1 else "a"
    if variant not in {"a", "b"}:
        raise ValueError("Variant must be a or b.")
    return source, variant


def _channel_keyboard(channel_url: str, promo_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 شرکت در مسابقه", url=promo_link)],
        [InlineKeyboardButton("📢 کانال الان چنده؟", url=channel_url)],
    ])


def _preview_keyboard(channel_url: str, promo_link: str, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 شرکت در مسابقه", url=promo_link)],
        [InlineKeyboardButton("📢 کانال الان چنده؟", url=channel_url)],
        [
            InlineKeyboardButton("✅ انتشار در کانال", callback_data=f"publishpromo:yes:{token}"),
            InlineKeyboardButton("❌ لغو", callback_data=f"publishpromo:no:{token}"),
        ],
    ])


async def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username
    if not username:
        raise RuntimeError("bot username is unavailable")
    return username


async def cmd_publish_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prepare an exact channel-post preview and require explicit confirmation."""
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    if not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("برای امنیت، این دستور را فقط در چت خصوصی با ربات ارسال کن.")
        return

    try:
        source, variant = parse_publish_args(list(context.args or []))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text("مسابقه فعالی برای انتشار وجود ندارد.")
        return

    try:
        username = await _bot_username(context)
    except Exception:
        log.exception("Could not resolve bot username for publish preview")
        await update.message.reply_text("نام کاربری ربات در دسترس نیست؛ کمی بعد دوباره تلاش کن.")
        return

    promo_link = build_promo_link(username, source, variant)
    text = promo_post_text(campaign, promo_link, variant)
    token = secrets.token_urlsafe(6)
    previews = context.application.bot_data.setdefault("publish_promo_previews", {})
    previews[token] = {
        "admin_id": int(update.effective_user.id),
        "campaign_id": campaign.id,
        "campaign_slug": campaign.slug,
        "source": source,
        "variant": variant,
        "promo_link": promo_link,
        "text": text,
        "expires_at": time.time() + _PREVIEW_TTL_SECONDS,
        "busy": False,
    }

    await update.message.reply_text(
        "🔎 پیش‌نمایش پست کانال\n"
        f"Source: {source}_{variant}\n\n"
        "اگر همه‌چیز درست است، دکمه «✅ انتشار در کانال» را بزن.\n"
        "این پیش‌نمایش بعد از ۱۵ دقیقه منقضی می‌شود."
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_preview_keyboard(settings.channel_url, promo_link, token),
        disable_web_page_preview=True,
    )


async def on_publish_promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    settings, db = services(context)
    if not query or not update.effective_user:
        return
    if not is_admin(update, settings):
        await query.answer("اجازه این کار را نداری.", show_alert=True)
        return

    parts = (query.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "publishpromo":
        await query.answer("درخواست نامعتبر است.", show_alert=True)
        return
    action, token = parts[1], parts[2]
    previews = context.application.bot_data.setdefault("publish_promo_previews", {})
    preview = previews.get(token)
    if not preview:
        await query.answer("این پیش‌نمایش منقضی شده؛ دوباره /publish_promo را اجرا کن.", show_alert=True)
        return
    if int(preview["admin_id"]) != int(update.effective_user.id):
        await query.answer("فقط ادمینی که پیش‌نمایش را ساخته می‌تواند آن را منتشر کند.", show_alert=True)
        return
    if time.time() > float(preview["expires_at"]):
        previews.pop(token, None)
        await query.answer("این پیش‌نمایش منقضی شده؛ دوباره دستور را اجرا کن.", show_alert=True)
        return

    if action == "no":
        previews.pop(token, None)
        await query.answer("لغو شد.")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        if query.message:
            await query.message.reply_text("❌ انتشار در کانال لغو شد.")
        return

    if action != "yes":
        await query.answer("درخواست نامعتبر است.", show_alert=True)
        return
    if preview.get("busy"):
        await query.answer("در حال انتشار است…", show_alert=True)
        return

    campaign = db.live_campaign()
    if not campaign or campaign.id != int(preview["campaign_id"]):
        previews.pop(token, None)
        await query.answer("مسابقه تغییر کرده یا دیگر فعال نیست؛ پیش‌نمایش جدید بساز.", show_alert=True)
        return

    preview["busy"] = True
    await query.answer("در حال انتشار…")
    try:
        sent = await context.bot.send_message(
            chat_id=settings.channel_ref,
            text=str(preview["text"]),
            parse_mode=ParseMode.HTML,
            reply_markup=_channel_keyboard(settings.channel_url, str(preview["promo_link"])),
            disable_web_page_preview=True,
        )
    except (Forbidden, BadRequest) as exc:
        preview["busy"] = False
        log.warning("Could not publish promo to channel: %s", exc)
        if query.message:
            await query.message.reply_text(
                "❌ انتشار انجام نشد. بررسی کن @Alanchandebot در کانال دسترسی «Post Messages / ارسال پیام» داشته باشد.\n"
                f"Telegram: {exc}"
            )
        return
    except TelegramError as exc:
        preview["busy"] = False
        log.exception("Telegram error while publishing promo")
        if query.message:
            await query.message.reply_text(f"❌ خطای تلگرام هنگام انتشار: {type(exc).__name__}")
        return

    previews.pop(token, None)
    db.log_admin_action(
        campaign.id,
        int(update.effective_user.id),
        "publish_promo",
        {
            "source": preview["source"],
            "variant": preview["variant"],
            "channel": str(settings.channel_ref),
            "message_id": int(sent.message_id),
            "promo_link": preview["promo_link"],
        },
    )

    try:
        await query.edit_message_reply_markup(
            reply_markup=_channel_keyboard(settings.channel_url, str(preview["promo_link"]))
        )
    except BadRequest:
        pass
    if query.message:
        await query.message.reply_text(
            "✅ پست با موفقیت در @alanchande_com منتشر شد.\n"
            f"Source: {preview['source']}_{preview['variant']}\n"
            f"Message ID: {sent.message_id}"
        )
