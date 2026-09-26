from __future__ import annotations

from datetime import timedelta, timezone
from html import escape
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telegram import CopyTextButton
except ImportError:  # Compatibility with older python-telegram-bot 21.x builds.
    CopyTextButton = None

from referral_core import Campaign, ReferralDB, utcnow
from .config import Settings, hours_label, remaining_label

ISTANBUL = timezone(timedelta(hours=3))
IRAN = timezone(timedelta(hours=3, minutes=30))


def main_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 لینک دعوت من", callback_data="menu:link")],
        [InlineKeyboardButton("📊 وضعیت من", callback_data="menu:stats"),
         InlineKeyboardButton("👥 دعوت‌های من", callback_data="menu:referrals")],
        [InlineKeyboardButton("🏆 جدول مسابقه", callback_data="menu:top"),
         InlineKeyboardButton("🎁 جوایز", callback_data="menu:prizes")],
        [InlineKeyboardButton("📜 قوانین", callback_data="menu:rules"),
         InlineKeyboardButton("🛡 شفافیت", callback_data="menu:trust")],
        [InlineKeyboardButton("📢 کانال الان چنده؟", url=settings.channel_url)],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:main")]])


def copy_link_button(link: str) -> InlineKeyboardButton:
    """Return Telegram's native copy button when supported, otherwise a safe fallback."""
    if CopyTextButton is not None:
        return InlineKeyboardButton(
            "📋 کپی لینک",
            copy_text=CopyTextButton(text=link),
        )
    return InlineKeyboardButton("🔗 نمایش لینک", callback_data="menu:link")


def invitation_share_url(link: str, campaign: Campaign | None = None) -> str:
    if campaign:
        share_text = (
            f"🎁 بیا در مسابقه {campaign.name} «الان چنده؟» شرکت کن!\n"
            f"🏆 {campaign.num_winners} برنده داریم.\n\n"
            "با لینک من وارد ربات شو؛ بعد از عضویت، خودت هم لینک اختصاصی می‌گیری 👇"
        )
    else:
        share_text = (
            "🎁 بیا در مسابقه «الان چنده؟» شرکت کن!\n"
            "با لینک من وارد شو 👇"
        )

    return "https://t.me/share/url?" + urlencode({
        "url": link,
        "text": share_text,
    })


def leaderboard_keyboard(link: str | None, campaign: Campaign) -> InlineKeyboardMarkup:
    # A visitor without a personal link must use the existing membership flow.
    invite = (
        InlineKeyboardButton("📤 دعوت از یک دوست", url=invitation_share_url(link, campaign))
        if link else InlineKeyboardButton("🔗 دریافت لینک دعوت من", callback_data="menu:link")
    )
    return InlineKeyboardMarkup([
        [invite],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:main")],
    ])


def link_keyboard(settings: Settings, link: str, campaign: Campaign | None = None) -> InlineKeyboardMarkup:
    share_url = invitation_share_url(link, campaign)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال لینک برای دوستان", url=share_url)],
        [copy_link_button(link)],
        [InlineKeyboardButton("📊 وضعیت و امتیاز من", callback_data="menu:stats")],
        [InlineKeyboardButton("⬅️ منوی مسابقه", callback_data="menu:main")],
    ])


def referral_activation_keyboard(
    settings: Settings,
    link: str,
    campaign: Campaign,
) -> InlineKeyboardMarkup:
    """First-session share CTA for participants acquired through a referral."""
    del settings  # Reserved for future channel-aware share copy.

    contest_hook = (
        "قرعه‌کشی ۲۱ میلیون تومانی «الان چنده؟»"
        if campaign.slug == "paeez1405"
        else f"مسابقه {campaign.name} «الان چنده؟»"
    )
    share_text = (
        f"🎁 دعوتت کردم به {contest_hook}\n"
        f"🏆 {campaign.num_winners} برنده داریم.\n\n"
        "اگر دوست داشتی شرکت کنی، از لینک من وارد شو و شرایط مسابقه رو ببین 👇"
    )
    share_url = "https://t.me/share/url?" + urlencode({
        "url": link,
        "text": share_text,
    })

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 همین الان برای ۱ نفر", url=share_url)],
        [copy_link_button(link)],
        [InlineKeyboardButton("📊 وضعیت و امتیاز من", callback_data="menu:stats")],
        [InlineKeyboardButton("⬅️ منوی مسابقه", callback_data="menu:main")],
    ])


def no_campaign_text() -> str:
    return "در حال حاضر مسابقه فعالی وجود ندارد. 🎁\n\nزمان شروع مسابقه بعدی از طریق کانال اعلام می‌شود."


def draw_schedule_text(campaign: Campaign) -> str:
    draw_local = campaign.draw_dt.astimezone(ISTANBUL)
    draw_iran = campaign.draw_dt.astimezone(IRAN)
    return (
        f"{draw_local:%Y/%m/%d} ساعت {draw_local:%H:%M} به وقت استانبول "
        f"/ {draw_iran:%Y/%m/%d} ساعت {draw_iran:%H:%M} به وقت ایران"
    )


def campaign_end_text(campaign: Campaign) -> str:
    end_ist = campaign.end_dt.astimezone(ISTANBUL)
    end_ir = campaign.end_dt.astimezone(IRAN)
    return (
        f"{end_ist:%Y/%m/%d} ساعت {end_ist:%H:%M} استانبول "
        f"/ {end_ir:%Y/%m/%d} ساعت {end_ir:%H:%M} ایران"
    )


def final_join_cutoff_text(campaign: Campaign) -> str:
    cutoff_ist = campaign.final_qualification_cutoff.astimezone(ISTANBUL)
    cutoff_ir = campaign.final_qualification_cutoff.astimezone(IRAN)
    return (
        f"{cutoff_ist:%Y/%m/%d} ساعت {cutoff_ist:%H:%M} استانبول "
        f"/ {cutoff_ir:%Y/%m/%d} ساعت {cutoff_ir:%H:%M} ایران"
    )


def _late_referral_warning(campaign: Campaign) -> str:
    if campaign.min_stay_hours <= 0 or utcnow() < campaign.final_qualification_cutoff:
        return ""
    return (
        "\n\n⚠️ <b>توجه:</b> از این زمان به بعد، دعوت جدید تا زمان قرعه‌کشی فرصت "
        f"کامل کردن {hours_label(campaign.min_stay_hours)} را ندارد و به بلیت تأییدشده تبدیل نمی‌شود."
    )


def menu_text(campaign: Campaign, first_name: str) -> str:
    return (
        f"سلام {escape(first_name or 'دوست عزیز')} 👋\n\n"
        f"<b>🎁 {escape(campaign.name)}</b>\n\n"
        "لینک اختصاصی‌ات را برای دوستانت بفرست. آن‌ها باید اول از لینک تو وارد ربات شوند و بعد عضو کانال شوند.\n\n"
        f"⭐ هر <b>{campaign.invites_per_point} دعوت فعال</b> = <b>۱ امتیاز موقت</b>\n"
        f"🎟 بعد از <b>{hours_label(campaign.min_stay_hours)}</b> عضویت پیوسته، همان امتیاز به <b>بلیت تأییدشده قرعه‌کشی</b> تبدیل می‌شود.\n\n"
        f"⏳ <b>آخرین زمان ورود دعوت جدید برای تأیید:</b> {final_join_cutoff_text(campaign)}\n"
        f"⏰ <b>پایان ثبت دعوت:</b> {campaign_end_text(campaign)}\n"
        f"📅 <b>زمان قرعه‌کشی:</b> {draw_schedule_text(campaign)}\n\n"
        f"در پایان <b>{campaign.num_winners} برنده</b> با قرعه‌کشی وزن‌دار انتخاب می‌شوند؛ "
        "هر بلیت تأییدشده شانس تو را بیشتر می‌کند."
        f"{_late_referral_warning(campaign)}"
    )


def render_home(campaign: Campaign, db: ReferralDB, user_id: int, first_name: str) -> str:
    """Compact action-first home card for an active participant."""
    counts = db.campaign_counts(campaign, user_id)
    pending_opens = db.pending_referral_count(campaign.id, user_id)
    closest = db.closest_pending_seconds(campaign, user_id)

    if campaign.max_points and counts["current_points"] >= campaign.max_points:
        progress = "✅ سقف امتیاز موقت این مسابقه را گرفته‌ای."
        next_action = "دعوت‌های فعالت را تا زمان تأیید حفظ کن."
    else:
        remainder = counts["active"] % campaign.invites_per_point
        need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point
        filled = int(round((remainder / campaign.invites_per_point) * 10))
        bar = "█" * filled + "░" * (10 - filled)
        progress = (
            f"🎯 تا امتیاز موقت بعدی: <b>{bar}</b> "
            f"{remainder}/{campaign.invites_per_point}"
        )
        if counts["active"] == 0:
            next_action = (
                f"اولین هدف: همین الان لینک را برای چند نفر بفرست؛ "
                f"با <b>{campaign.invites_per_point}</b> دعوت فعال اولین امتیازت را می‌گیری."
            )
        elif need == 1:
            next_action = "🔥 فقط <b>۱ دعوت فعال</b> دیگر تا امتیاز موقت بعدی."
        else:
            next_action = f"🔥 فقط <b>{need}</b> دعوت فعال دیگر تا امتیاز موقت بعدی."

    open_line = (
        f"👀 <b>{pending_opens}</b> نفر لینک را باز کرده‌اند و هنوز عضویت را کامل نکرده‌اند.\n"
        if pending_opens else ""
    )
    closest_line = (
        f"⏳ نزدیک‌ترین تأیید: <b>{remaining_label(closest)}</b> دیگر\n"
        if closest is not None else ""
    )

    return (
        f"سلام {escape(first_name or 'دوست عزیز')} 👋\n\n"
        f"<b>🏆 وضعیت تو — {escape(campaign.name)}</b>\n\n"
        f"👥 دعوت فعال: <b>{counts['active']}</b>\n"
        f"⭐ امتیاز موقت: <b>{counts['current_points']}</b>\n"
        f"🎟 بلیت تأییدشده: <b>{counts['confirmed_points']}</b>\n"
        f"⏳ در انتظار تأیید: <b>{counts['pending']}</b>\n"
        f"{open_line}{closest_line}\n"
        f"{progress}\n"
        f"{next_action}\n\n"
        "👇 <b>کار بعدی:</b> لینک اختصاصی‌ات را برای دوستانت بفرست."
        f"{_late_referral_warning(campaign)}"
    )


def render_stats(campaign: Campaign, db: ReferralDB, user_id: int) -> str:
    counts = db.campaign_counts(campaign, user_id)
    pending_opens = db.pending_referral_count(campaign.id, user_id)
    rank, ranked_total = db.leaderboard_position(campaign, user_id)
    closest = db.closest_pending_seconds(campaign, user_id)

    if campaign.max_points and counts["current_points"] >= campaign.max_points:
        next_text = "✅ به سقف امتیاز موقت این مسابقه رسیده‌ای."
        progress_text = "🎯 پیشرفت امتیاز بعدی: سقف مسابقه تکمیل شده است."
    else:
        remainder = counts["active"] % campaign.invites_per_point
        need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point
        filled = int(round((remainder / campaign.invites_per_point) * 10)) if campaign.invites_per_point else 0
        progress_bar = "█" * filled + "░" * (10 - filled)
        next_text = f"🔥 تا امتیاز موقت بعدی فقط <b>{need}</b> دعوت فعال دیگر لازم داری."
        progress_text = (
            f"🎯 پیشرفت امتیاز بعدی: <b>{progress_bar}</b> "
            f"{remainder}/{campaign.invites_per_point}"
        )

    rank_text = (
        f"📍 رتبه فعلی تو: <b>#{rank}</b> از <b>{ranked_total}</b> نفر"
        if rank is not None else
        f"📍 هنوز وارد جدول امتیازی نشده‌ای؛ جدول فعلاً <b>{ranked_total}</b> نفر دارد."
    )
    pending_open_text = (
        f"👀 <b>{pending_opens}</b> نفر لینک تو را باز کرده‌اند ولی هنوز عضویت را کامل نکرده‌اند."
        if pending_opens else "👀 دعوت ناتمام از لینک تو نداری."
    )
    closest_text = (
        f"⏳ نزدیک‌ترین تأیید: <b>{remaining_label(closest)}</b> دیگر"
        if closest is not None else ""
    )

    retention_note = (
        "⭐ <b>موقت</b> یعنی دوستت الان عضو کانال است و اگر خارج شود کم می‌شود.\n"
        f"🎟 <b>تأییدشده</b> یعنی حداقل {hours_label(campaign.min_stay_hours)} مانده و فقط این بلیت در قرعه‌کشی حساب می‌شود."
        if campaign.min_stay_hours > 0
        else "✅ امتیاز موقت و بلیت قرعه‌کشی در این مسابقه بلافاصله تأیید می‌شوند."
    )

    extra = f"\n{closest_text}" if closest_text else ""
    return (
        f"<b>📊 وضعیت من — {escape(campaign.name)}</b>\n\n"
        f"⭐ امتیاز موقت: <b>{counts['current_points']}</b>\n"
        f"🎟 بلیت تأییدشده: <b>{counts['confirmed_points']}</b>\n\n"
        f"👥 دعوت فعال: <b>{counts['active']}</b>\n"
        f"✅ دعوت تأییدشده: <b>{counts['qualified']}</b>\n"
        f"⏳ در انتظار تأیید: <b>{counts['pending']}</b>\n"
        f"❌ خارج‌شده: <b>{counts['left']}</b>\n\n"
        f"{progress_text}\n{next_text}\n{rank_text}\n{pending_open_text}{extra}\n\n"
        f"⏳ <b>آخرین زمان ورود دعوت جدید برای تأیید:</b> {final_join_cutoff_text(campaign)}\n\n"
        f"{retention_note}"
        f"{_late_referral_warning(campaign)}"
    )


def render_referrals(campaign: Campaign, db: ReferralDB, user_id: int) -> str:
    rows = db.referral_list(campaign, user_id, limit=15)
    pending_opens = db.pending_referral_count(campaign.id, user_id)
    if not rows:
        suffix = (
            f"\n\n👀 {pending_opens} نفر لینک را باز کرده‌اند ولی هنوز عضویت را کامل نکرده‌اند."
            if pending_opens else ""
        )
        return "<b>👥 دعوت‌های من</b>\n\nهنوز کسی از طریق لینک اختصاصی تو عضو کانال نشده است." + suffix
    lines = ["<b>👥 دعوت‌های من</b>\n"]
    for row in rows:
        label = escape(row["first_name"] or ("@" + row["username"] if row["username"] else "کاربر تلگرام"))
        if row["username"] and row["first_name"]:
            label += f" (@{escape(row['username'])})"
        if row["status"] == "qualified":
            status = "✅ تأییدشده"
        elif row["status"] == "left":
            status = "❌ خارج شده — اگر برگردد، زمان تأیید از صفر شروع می‌شود"
        elif not row.get("can_qualify_by_draw", True):
            status = "⚠️ فعال، اما تا زمان قرعه‌کشی فرصت تکمیل دوره را ندارد"
        else:
            status = f"⏳ {remaining_label(row['remaining_seconds'])} تا تأیید"
        lines.append(f"• {label} — {status}")
    if pending_opens:
        lines.append(f"\n👀 <b>{pending_opens}</b> نفر لینک را باز کرده‌اند ولی هنوز عضویت را کامل نکرده‌اند.")
    if len(rows) == 15:
        lines.append("\nآخرین ۱۵ دعوت نمایش داده شده است.")
    return "\n".join(lines)


def _mask_name(first_name: str | None, username: str | None, user_id: int) -> str:
    raw = (first_name or username or "").strip()
    if raw:
        visible = raw[:2]
        return escape(visible + "***")
    return f"کاربر ***{str(user_id)[-3:]}"


def render_top(campaign: Campaign, db: ReferralDB, user_id: int | None = None) -> str:
    # Set each paragraph's base direction before any Latin name or neutral emoji.
    rtl = "\u200f"
    digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    number = lambda value: str(value).translate(digits)
    # Names can contain their own directional controls; do not let those escape
    # the isolate or consume the two visible characters used for masking.
    controls = dict.fromkeys(map(ord, "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
    title = f"{rtl}<b>🏆 جدول مسابقه — {escape(campaign.name)}</b>"
    rows = db.leaderboard(campaign, limit=10)
    if not rows:
        return (
            f"{title}\n\n"
            f"{rtl}هنوز امتیازی در جدول ثبت نشده؛ اولین نفر باش! 🚀"
        )
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{title}\n{rtl}بر اساس امتیاز موقت"]
    for index, row in enumerate(rows):
        badge = f"{medals[index]} " if index < 3 else ""
        name = _mask_name(
            (row["first_name"] or "").translate(controls),
            (row["username"] or "").translate(controls),
            row["user_id"],
        )
        lines.append(
            f"{rtl}{number(index + 1)}) {badge}\u2068<b>{name}</b>\u2069\n"
            f"{rtl}⭐ امتیاز موقت: <b>{number(row['current_points'])}</b> | "
            f"🎟 بلیت تأییدشده: <b>{number(row['confirmed_points'])}</b>"
        )
    if user_id is not None:
        rank, total = db.leaderboard_position(campaign, user_id)
        if rank is not None:
            lines.append(f"{rtl}📍 رتبه تو: <b>{number(rank)}</b> از <b>{number(total)}</b>")
    lines.append(
        f"{rtl}ℹ️ این جدول فقط پیشرفت فعلی را نشان می‌دهد و ترتیب آن تعیین‌کننده برنده نیست. "
        "برندگان با قرعه‌کشی وزن‌دار و فقط بر اساس 🎟 بلیت‌های تأییدشده انتخاب می‌شوند."
    )
    return "\n\n".join(lines)


def render_rules(campaign: Campaign) -> str:
    cap = (f"حداکثر بلیت قابل استفاده در قرعه‌کشی <b>{campaign.max_points}</b> است."
           if campaign.max_points else "برای بلیت‌ها سقفی تعیین نشده است.")
    return (
        f"<b>📜 قوانین {escape(campaign.name)}</b>\n\n"
        "<b>خلاصه:</b>\n"
        f"• هر {campaign.invites_per_point} دعوت فعال = ۱ ⭐ امتیاز موقت\n"
        f"• بعد از {hours_label(campaign.min_stay_hours)} ماندن = ۱ 🎟 بلیت تأییدشده\n"
        "• خروج از کانال امتیاز را کم می‌کند؛ بازگشت زمان را از صفر شروع می‌کند\n"
        "• برندگان با قرعه‌کشی وزن‌دار انتخاب می‌شوند\n\n"
        "1️⃣ لینک اختصاصی خودت را فقط از همین ربات دریافت کن.\n\n"
        "2️⃣ دوستت باید ابتدا از لینک اختصاصی تو وارد ربات شود و سپس عضو کانال شود.\n\n"
        f"3️⃣ هر <b>{campaign.invites_per_point}</b> دعوت فعال، ۱ ⭐ امتیاز موقت ایجاد می‌کند. "
        f"پس از <b>{hours_label(campaign.min_stay_hours)}</b> عضویت پیوسته، به 🎟 بلیت تأییدشده تبدیل می‌شود.\n\n"
        "4️⃣ اگر دوستت خارج شود، سهم او کم می‌شود. اگر دوباره عضو شود، زمان انتظار از صفر شروع می‌شود.\n\n"
        "5️⃣ هر حساب تلگرام در هر مسابقه فقط یک‌بار و برای اولین معرف ثبت‌شده حساب می‌شود.\n\n"
        "6️⃣ حساب‌های فیک یا تلاش برای دستکاری مسابقه می‌تواند پس از بررسی باعث حذف شود.\n\n"
        "7️⃣ فقط 🎟 بلیت‌های تأییدشده در قرعه‌کشی نهایی وزن دارند و هر نفر حداکثر یک بار برنده می‌شود.\n\n"
        "8️⃣ قبل از فریز فهرست قرعه‌کشی، عضویت دعوت‌شده‌ها و شرکت‌کنندگان دوباره بررسی می‌شود.\n\n"
        f"9️⃣ ⏰ پایان ثبت دعوت: <b>{campaign_end_text(campaign)}</b>\n"
        f"📅 زمان فریز فهرست/قرعه‌کشی: <b>{draw_schedule_text(campaign)}</b>\n\n"
        f"🔟 آخرین زمان عضویت یک دعوت جدید برای تکمیل دوره تا قرعه‌کشی: <b>{final_join_cutoff_text(campaign)}</b>\n\n"
        f"1️⃣1️⃣ {cap}"
        f"{_late_referral_warning(campaign)}"
    )


def render_prizes(campaign: Campaign) -> str:
    prize = escape(campaign.prize_text) if campaign.prize_text else "جزئیات جایزه به‌زودی اعلام می‌شود."
    return (
        f"<b>🎁 جوایز — {escape(campaign.name)}</b>\n\n{prize}\n\n"
        f"🏆 تعداد برندگان: <b>{campaign.num_winners}</b> نفر\n"
        f"⏳ آخرین زمان ورود دعوت جدید برای تأیید: <b>{final_join_cutoff_text(campaign)}</b>\n"
        f"⏰ پایان ثبت دعوت: <b>{campaign_end_text(campaign)}</b>\n"
        f"📅 زمان قرعه‌کشی: <b>{draw_schedule_text(campaign)}</b>"
    )


def render_transparency(campaign: Campaign) -> str:
    lock = "✅ قوانین امتیازدهی بعد از فعال‌شدن مسابقه قفل شده‌اند." if campaign.rules_locked_at else "⚠️ قوانین هنوز قفل نشده‌اند."
    return (
        f"<b>🛡 شفافیت قرعه‌کشی — {escape(campaign.name)}</b>\n\n"
        f"{lock}\n\n"
        "🔎 قبل از قرعه‌کشی، عضویت‌ها دوباره بررسی می‌شوند و فهرست نهایی شرکت‌کنندگان فریز می‌شود.\n\n"
        "🔐 از فهرست نهایی یک SHA-256 منتشر می‌شود تا بعداً مشخص باشد فهرست دستکاری نشده است.\n\n"
        "₿ منبع تصادفی قرعه‌کشی: اولین بلاک بیت‌کوین بعد از زمان فریز فهرست. هش بلاک، Seed نهایی را می‌سازد و قابل بررسی عمومی است.\n\n"
        "🏆 ۵ برنده اصلی و فهرست ذخیره از همان اجرای واحد قرعه‌کشی تولید می‌شوند؛ جایگزین برنده ردشده توسط ادمین انتخاب نمی‌شود.\n\n"
        "📦 بعد از قرعه‌کشی، هش فهرست، Seed، منبع Seed، نسخه کد و نتیجه منتشر می‌شود.\n\n"
        f"📅 زمان برنامه‌ریزی‌شده: <b>{draw_schedule_text(campaign)}</b>"
    )
