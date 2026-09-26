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
    back_keyboard, leaderboard_keyboard, link_keyboard, main_keyboard, menu_text, no_campaign_text,
    render_home, render_prizes, render_referrals, render_rules, render_stats, render_top,
    render_transparency,
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


def pending_join_keyboard(settings: Settings, campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ ورود به کانال و عضویت", url=settings.channel_url)],
        [InlineKeyboardButton("✅ عضو شدم؛ بررسی کن", callback_data=f"ref:check:{campaign_id}")],
    ])


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


def referral_join_progress_message(
    campaign: Campaign,
    counts: dict,
    result: str,
) -> tuple[str, str, bool]:
    """Render the immediate referrer progress message after a join/rejoin."""
    if result == "reactivated":
        return (
            "🔄 <b>یکی از دعوت‌شده‌هات دوباره عضو شد.</b>\n\n"
            "⏳ زمان تأیید او از صفر شروع شد.\n"
            f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>",
            "📤 دعوت نفر بعدی",
            False,
        )

    remainder = counts["active"] % campaign.invites_per_point
    need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point

    # The highest-value state for the current contest: one active referral
    # means the participant is exactly one person away from the next point.
    if campaign.invites_per_point == 2 and remainder == 1:
        first_point = counts["current_points"] == 0
        title = (
            "🔥 <b>عالیه! اولین دعوتت ثبت شد ✅</b>"
            if first_point
            else "🔥 <b>یک دعوت جدید ثبت شد ✅</b>"
        )
        progress_name = "اولین امتیاز" if first_point else "امتیاز بعدی"
        return (
            f"{title}\n\n"
            f"🎯 <b>پیشرفت {progress_name}:</b>\n"
            "█████░░░░░ <b>۱/۲</b>\n\n"
            "فقط <b>۱ نفر دیگه</b> مونده تا امتیاز موقتت ساخته بشه.\n\n"
            f"🎟 اگر این دوست <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته بماند، "
            "سهم این دعوت برای قرعه‌کشی تأیید می‌شود.",
            "📤 فقط ۱ نفر دیگه",
            True,
        )

    return (
        "🎉 <b>یک نفر جدید با لینک تو عضو شد!</b>\n\n"
        f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>\n"
        f"🔥 تا امتیاز موقت بعدی: <b>{need}</b> دعوت فعال\n\n"
        f"🎟 اگر این دوست <b>{hours_label(campaign.min_stay_hours)}</b> پیوسته بماند، "
        "سهمش برای قرعه‌کشی تأیید می‌شود.",
        "📤 دعوت نفر بعدی",
        False,
    )


async def notify_referral_join(context: ContextTypes.DEFAULT_TYPE, campaign: Campaign, user,
                               referrer_id: int, result: str | None) -> None:
    if result not in {"created", "reactivated"}:
        return
    _, db = services(context)
    counts = db.campaign_counts(campaign, referrer_id)
    text, share_button_text, one_more_prompt = referral_join_progress_message(
        campaign,
        counts,
        result,
    )
    log.info(
        "Referral %s: joined=%s referrer=%s campaign=%s",
        result, user.id, referrer_id, campaign.slug,
    )
    if result == "created":
        db.track_funnel_event(campaign.id, user.id, "join_confirmed", "referral")
    else:
        db.track_funnel_event(campaign.id, user.id, "rejoin", "")
    try:
        await context.bot.send_message(
            referrer_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(share_button_text, callback_data="menu:link"),
                InlineKeyboardButton("📊 وضعیت من", callback_data="menu:stats"),
            ]]),
        )
        if one_more_prompt:
            db.track_funnel_event(
                campaign.id,
                referrer_id,
                "referral_one_more_prompt_sent",
                "referral",
            )
    except (Forbidden, BadRequest):
        pass
    except TelegramError:
        log.exception("Could not notify referrer %s", referrer_id)


async def finalize_pending_referral(context: ContextTypes.DEFAULT_TYPE, campaign: Campaign, user) -> str:
    """Atomically convert a pending referral once channel membership is confirmed."""
    _, db = services(context)
    result, referrer_id = db.finalize_pending_join(
        campaign, user.id, user.username, user.first_name,
    )
    if referrer_id is not None:
        await notify_referral_join(context, campaign, user, referrer_id, result)
    return result


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
        await update.message.reply_text("فعلاً نتونستم عضویتت رو بررسی کنم. لطفاً کمی بعد دوباره همین لینک رو باز کن.")
        return True

    if already_member:
        if db.pending_referrer(campaign.id, user.id) is not None:
            result = await finalize_pending_referral(context, campaign, user)
            if result in {"created", "reactivated", "duplicate", "already_recorded"}:
                await update.message.reply_text("✅ عضویتت تأیید شد و دعوت ثبت شده است.")
                from .referral_success import send_participant_welcome
                await send_participant_welcome(context, campaign, user)
                return True

        if db.referrer_for_joined(campaign.id, user.id) is not None:
            await update.message.reply_text("✅ دعوت این حساب قبلاً در همین مسابقه ثبت شده است.")
            from .referral_success import send_participant_welcome
            await send_participant_welcome(context, campaign, user)
            return True

        # Existing members cannot become a new referral, but they should still be able to participate.
        try:
            link = await get_or_create_link(context, campaign, user)
            db.track_funnel_event(campaign.id, user.id, "entered_contest", "existing_member")
            db.track_funnel_event(campaign.id, user.id, "link_created", "existing_member")
            await update.message.reply_text(
                "تو از قبل عضو کانال بودی؛ بنابراین برای معرف جدید حساب نمی‌شی. "
                "اما خودت می‌تونی همین الان در مسابقه شرکت کنی 👇\n\n"
                f"🔗 لینک اختصاصی تو:\n{link}",
                reply_markup=link_keyboard(settings, link, campaign),
                disable_web_page_preview=True,
            )
        except Exception:
            log.exception("Could not onboard existing channel member")
            await update.message.reply_text("ساخت لینک اختصاصی فعلاً ممکن نشد. کمی بعد دوباره تلاش کن.")
        return True

    result, assigned_referrer = db.create_pending_referral(
        campaign, user.id, referrer_id, user.username, user.first_name,
    )
    db.track_funnel_event(campaign.id, user.id, "pending_created", "referral")
    if result == "self":
        await update.message.reply_text("دعوت خودت قابل ثبت نیست.")
        return True

    if assigned_referrer != referrer_id:
        text = (
            "این حساب قبلاً در همین مسابقه به یک معرف دیگر نسبت داده شده و معرف اول تغییر نمی‌کند.\n\n"
            "1️⃣ وارد کانال شو.\n2️⃣ روی Join Channel / عضویت بزن.\n"
            "3️⃣ بعد به <b>همین چت</b> برگرد و «✅ عضو شدم؛ بررسی کن» را بزن."
        )
    elif result == "existing_referral":
        text = "دعوت قبلی تو حفظ شده است. اگر دوباره عضو کانال شوی، زمان انتظار از صفر شروع می‌شود."
    else:
        text = (
            "👋 <b>دوستت تو رو به مسابقه دعوت کرده! 🎁</b>\n\n"
            "برای کامل‌شدن دعوت:\n"
            "1️⃣ دکمه «ورود به کانال و عضویت» را بزن.\n"
            "2️⃣ داخل کانال روی «Join Channel / عضویت» بزن.\n"
            "3️⃣ بعد به <b>همین چت</b> برگرد و «✅ عضو شدم؛ بررسی کن» را بزن.\n\n"
            "بعدش خودت هم لینک اختصاصی می‌گیری و می‌تونی دوستات رو دعوت کنی. 🚀"
        )

    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=pending_join_keyboard(settings, campaign.id),
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
            "برای شرکت در مسابقه اول عضو کانال شو؛ بعد به همین چت برگرد. 👇",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 عضویت در کانال", url=settings.channel_url)]]),
        )
        return
    existing_link = db.get_invite_link(campaign.id, user.id)
    try:
        link = await get_or_create_link(context, campaign, user)
    except Exception:
        log.exception("Could not create referral deep link for %s", user.id)
        await update.message.reply_text("ساخت لینک اختصاصی با خطا روبه‌رو شد. لطفاً کمی بعد دوباره تلاش کن.")
        return

    if existing_link:
        await update.message.reply_text(
            render_home(campaign, db, user.id, user.first_name),
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(settings),
            disable_web_page_preview=True,
        )
        return

    db.track_funnel_event(campaign.id, user.id, "entered_contest", "organic")
    db.track_funnel_event(campaign.id, user.id, "link_created", "organic")
    first_step = (
        "👥 اولین دعوت فعال = نصف راه تا اولین امتیاز"
        if campaign.invites_per_point == 2
        else f"👥 برای اولین امتیاز به {campaign.invites_per_point} دعوت فعال نیاز داری"
    )
    await update.message.reply_text(
        "🎉 <b>وارد مسابقه شدی و لینک اختصاصی‌ات آماده است.</b>\n\n"
        f"<b>🔗 لینک تو:</b>\n{link}\n\n"
        f"{first_step}\n"
        f"🎯 الان <b>۰ از {campaign.invites_per_point}</b> تا اولین امتیاز موقت\n\n"
        "📤 بهترین کار اینه که همین الان لینک رو برای ۲–۳ نفر بفرستی؛ "
        "وقتی یکی از آن‌ها لینک را باز کند همینجا بهت خبر می‌دیم.",
        parse_mode=ParseMode.HTML,
        reply_markup=link_keyboard(settings, link, campaign),
        disable_web_page_preview=True,
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
        render_home(campaign, db, user.id, user.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(settings),
        disable_web_page_preview=True,
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


async def on_referral_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Legacy callback kept for compatibility; the registered handler lives in referral_success.py.
    from .referral_success import on_referral_check_and_welcome
    await on_referral_check_and_welcome(update, context)


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
        text, markup = render_home(campaign, db, user.id, user.first_name), main_keyboard(settings)
    elif data == "menu:stats":
        text = render_stats(campaign, db, user.id)
    elif data == "menu:referrals":
        text = render_referrals(campaign, db, user.id)
    elif data == "menu:top":
        text = render_top(campaign, db, user.id)
        link = None
        payload = db.get_invite_link(campaign.id, user.id)
        if payload and payload.startswith("ref_"):
            try:
                username = context.bot.username
                if not username:
                    username = (await context.bot.get_me()).username
                if username:
                    link = f"https://t.me/{username}?start={payload}"
            except TelegramError:
                log.warning("Could not resolve bot username for leaderboard share button")
        markup = leaderboard_keyboard(link, campaign)
    elif data == "menu:rules":
        text = render_rules(campaign)
    elif data == "menu:prizes":
        text = render_prizes(campaign)
    elif data == "menu:trust":
        text = render_transparency(campaign)
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
                counts = db.campaign_counts(campaign, user.id)
                remainder = counts["active"] % campaign.invites_per_point
                need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point
                text = (
                    f"<b>🔗 لینک اختصاصی تو</b>\n\n{link}\n\n"
                    f"👥 دعوت فعال: <b>{counts['active']}</b>\n"
                    f"⭐ امتیاز موقت: <b>{counts['current_points']}</b>\n"
                    f"🎯 تا امتیاز موقت بعدی: <b>{need}</b> دعوت فعال\n\n"
                    "📤 همین الان برای چند نفر بفرست. دوستت باید اول این لینک را باز کند؛ "
                    "بعد ربات مرحله‌به‌مرحله عضویت را راهنمایی می‌کند."
                )
                markup = link_keyboard(settings, link, campaign)
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

        result, referrer_id = db.finalize_pending_join(
            campaign, user.id, user.username, user.first_name,
        )
        if referrer_id is not None and result in {"created", "reactivated"}:
            await notify_referral_join(context, campaign, user, referrer_id, result)
            from .referral_success import send_participant_welcome
            await send_participant_welcome(context, campaign, user)
            return

        referrer_id = db.reactivate_original(
            campaign.id, user.id, user.username, user.first_name,
        )
        if referrer_id is not None:
            await notify_referral_join(context, campaign, user, referrer_id, "reactivated")
            from .referral_success import send_participant_welcome
            await send_participant_welcome(context, campaign, user)
            return

        # Promo/organic entrants used to have to return to the bot and press a
        # second membership-check button. Complete their entry as soon as the
        # channel membership update arrives; the old button remains a fallback.
        from .promo_handlers import auto_complete_promo_join
        await auto_complete_promo_join(context, campaign, user)

    elif was_member and not is_member_now:
        campaign = db.live_campaign()
        referrer_id = db.referrer_for_joined(campaign.id, user.id) if campaign else None
        changed = db.mark_left(user.id)
        if changed:
            log.info("Referral member left: user=%s records=%s", user.id, changed)
            if campaign:
                db.track_funnel_event(campaign.id, user.id, "left", "")
            if campaign and referrer_id is not None:
                counts = db.campaign_counts(campaign, referrer_id)
                try:
                    await context.bot.send_message(
                        referrer_id,
                        "❌ <b>یکی از دعوت‌شده‌هات از کانال خارج شد.</b>\n\n"
                        f"⭐ امتیاز موقتت الان: <b>{counts['current_points']}</b>\n"
                        "اگر دوباره عضو شود، زمان تأییدش از صفر شروع می‌شود.",
                        parse_mode=ParseMode.HTML,
                    )
                except (Forbidden, BadRequest):
                    pass
                except TelegramError:
                    log.exception("Could not send referral-left notice referrer=%s", referrer_id)


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
                f"🎟 دعوت <b>{name}</b> تأیید شد!\n\n"
                f"✅ دعوت‌های تأییدشده: <b>{counts['qualified']}</b>\n"
                f"🎟 بلیت‌های تأییدشده قرعه‌کشی: <b>{counts['confirmed_points']}</b>\n"
                f"⭐ امتیاز موقت فعلی: <b>{counts['current_points']}</b>",
                parse_mode=ParseMode.HTML,
            )
            db.mark_qualification_notified(row["id"])
            db.track_funnel_event(campaign.id, row["joined_user_id"], "qualified", "")
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
