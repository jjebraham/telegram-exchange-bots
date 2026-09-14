from __future__ import annotations

import asyncio
import logging
import secrets
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
    """Return an unguessable Telegram bot deep link for this referrer/campaign."""
    _, db = services(context)
    existing = db.get_invite_link(campaign.id, user.id)
    if existing and existing.startswith("ref_"):
        payload = existing
    else:
        lock = _link_locks.setdefault((campaign.id, user.id), asyncio.Lock())
        async with lock:
            existing = db.get_invite_link(campaign.id, user.id)
            if existing and existing.startswith("ref_"):
                payload = existing
            else:
                payload = f"ref_{campaign.id}_{secrets.token_urlsafe(9)}"
                if existing:
                    db.replace_invite_link(campaign.id, user.id, payload)
                else:
                    db.save_invite_link(campaign.id, user.id, payload)

    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username
    if not username:
        raise RuntimeError("bot username is unavailable")
    return f"https://t.me/{username}?start={payload}"


async def handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                payload: str, user) -> bool:
    """Reserve referral attribution before a non-member joins the public channel."""
    settings, db = services(context)
    if not update.message:
        return True

    owner = db.invite_owner(payload)
    if not owner:
        await update.message.reply_text("این لینک دعوت معتبر نیست یا دیگر فعال نیست.")
        return True

    campaign, referrer_id = owner
    live = db.live_campaign()
    if not live or live.id != campaign.id:
        await update.message.reply_text("این لینک مربوط به مسابقه‌ای است که دیگر فعال نیست.")
        return True

    if user.id == referrer_id:
        await update.message.reply_text("نمی‌توانی با لینک خودت، خودت را به‌عنوان دعوت‌شده ثبت کنی. 🙂")
        return True

    try:
        already_member = await telegram_membership(context.bot, settings, user.id)
    except TelegramError:
        log.exception("Could not check referral candidate membership for %s", user.id)
        await update.message.reply_text("فعلاً نتوانستم عضویتت را بررسی کنم. لطفاً کمی بعد دوباره همین لینک را باز کن.")
        return True

    if already_member:
        await update.message.reply_text(
            "تو در حال حاضر عضو کانال هستی؛ بنابراین این لینک به‌عنوان دعوت جدید حساب نمی‌شود.\n\n"
            "اگر می‌خواهی خودت در مسابقه شرکت کنی، /start را بدون لینک دعوت بزن."
        )
        return True

    result, assigned_referrer = db.create_pending_referral(
        campaign, user.id, referrer_id, user.username, user.first_name,
    )
    if result == "self":
        await update.message.reply_text("دعوت خودت قابل ثبت نیست.")
        return True

    if assigned_referrer != referrer_id:
        text = (
            "این حساب قبلاً در همین مسابقه به یک معرف دیگر نسبت داده شده است. "
            "معرف اول تغییر نمی‌کند.\n\n"
            "برای تکمیل همان دعوت، حالا عضو کانال شو. 👇"
        )
    elif result == "existing_referral":
        text = "دعوت قبلی تو حفظ شده است. برای ادامه، دوباره عضو کانال شو. 👇"
    else:
        text = (
            "✅ دعوتت ثبت شد.\n\n"
            "حالا از دکمه زیر عضو کانال شو. بعد از عضویت، ربات به‌صورت خودکار دعوت را به معرفت وصل می‌کند."
        )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 عضویت در کانال الان چنده؟", url=settings.channel_url)]
        ]),
    )
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    user = update.effective_user
    if not user or not update.message:
        return
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)

    payload = context.args[0].strip() if context.args else ""
    if payload.startswith("ref_"):
        await handle_referral_start(update, context, payload, user)
        return

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
    except Exception:
        log.exception("Could not create referral deep link for %s", user.id)
        await update.message.reply_text("ساخت لینک اختصاصی با خطا روبه‌رو شد. لطفاً کمی بعد دوباره /start را بزن.")
        return
    await update.message.reply_text(
        menu_text(campaign, user.first_name), parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings), disable_web_page_preview=True,
    )
    await update.message.reply_text(
        f"<b>🔗 لینک اختصاصی تو:</b>\n\n{link}\n\n"
        "دوستت باید اول از این لینک وارد ربات شود و بعد با دکمه عضویت وارد کانال شود.",
        parse_mode=ParseMode.HTML,
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
                text = (
                    f"<b>🔗 لینک اختصاصی تو</b>\n\n{link}\n\n"
                    "این لینک را برای دوستانت بفرست. آن‌ها باید اول ربات را باز کنند و سپس از داخل ربات عضو کانال شوند."
                )
                markup = link_keyboard(settings, link)
            except Exception:
                log.exception("Could not create referral deep link")
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
        db.upsert_user(user.id, user.username, user.first_name, user.last_name)

        referrer_id = db.pop_pending_referrer(campaign.id, user.id)
        if referrer_id is not None:
            result = db.record_join(
                campaign, user.id, referrer_id, user.username, user.first_name,
            )
            await notify_referral_join(context, campaign, user, referrer_id, result)
            return

        # A previously referred user may rejoin without reopening the referral link.
        referrer_id = db.reactivate_original(
            campaign.id, user.id, user.username, user.first_name,
        )
        if referrer_id is not None:
            await notify_referral_join(context, campaign, user, referrer_id, "reactivated")

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
