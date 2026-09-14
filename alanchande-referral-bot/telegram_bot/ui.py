from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from referral_core import Campaign, ReferralDB
from .config import Settings, hours_label, remaining_label


def main_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 دعوت دوستان", callback_data="menu:link")],
        [InlineKeyboardButton("📊 امتیازهای من", callback_data="menu:stats"),
         InlineKeyboardButton("👥 دعوت‌های من", callback_data="menu:referrals")],
        [InlineKeyboardButton("🏆 جدول مسابقه", callback_data="menu:top"),
         InlineKeyboardButton("🎁 جوایز", callback_data="menu:prizes")],
        [InlineKeyboardButton("📜 قوانین", callback_data="menu:rules")],
        [InlineKeyboardButton("📢 کانال الان چنده؟", url=settings.channel_url)],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:main")]])


def link_keyboard(settings: Settings, link: str) -> InlineKeyboardMarkup:
    share_text = "برای شرکت در مسابقه الان چنده؟ اول از این لینک وارد ربات شو 👇"
    share_url = "https://t.me/share/url?" + urlencode({"url": link, "text": share_text})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال لینک برای دوستان", url=share_url)],
        [InlineKeyboardButton("📢 مشاهده کانال", url=settings.channel_url)],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:main")],
    ])


def no_campaign_text() -> str:
    return "در حال حاضر مسابقه فعالی وجود ندارد. 🎁\n\nزمان شروع مسابقه بعدی از طریق کانال اعلام می‌شود."


def menu_text(campaign: Campaign, first_name: str) -> str:
    return (
        f"سلام {escape(first_name or 'دوست عزیز')} 👋\n\n"
        f"<b>🎁 {escape(campaign.name)}</b>\n\n"
        f"لینک اختصاصی ربات را برای دوستانت بفرست. آن‌ها باید اول از لینک تو وارد ربات شوند و سپس عضو کانال شوند.\n"
        f"هر <b>{campaign.invites_per_point} عضو تأییدشده</b> = <b>۱ امتیاز 🎟</b>\n\n"
        f"هر دوست باید حداقل <b>{hours_label(campaign.min_stay_hours)}</b> به‌صورت پیوسته عضو کانال بماند.\n\n"
        f"در پایان <b>{campaign.num_winners} برنده</b> به‌صورت تصادفی انتخاب می‌شوند؛ "
        f"هرچه امتیاز بیشتری داشته باشی، شانس بیشتری برای برنده شدن داری."
    )


def render_stats(campaign: Campaign, db: ReferralDB, user_id: int) -> str:
    counts = db.campaign_counts(campaign, user_id)
    if campaign.max_points and counts["points"] >= campaign.max_points:
        next_text = "به سقف امتیاز این مسابقه رسیده‌ای. ✅"
    else:
        remainder = counts["qualified"] % campaign.invites_per_point
        need = campaign.invites_per_point - remainder if remainder else campaign.invites_per_point
        next_text = f"برای امتیاز بعدی به <b>{need}</b> دعوت تأییدشده دیگر نیاز داری."
    return (
        f"<b>📊 امتیازهای من — {escape(campaign.name)}</b>\n\n"
        f"✅ دعوت تأییدشده: <b>{counts['qualified']}</b>\n"
        f"⏳ در انتظار تأیید: <b>{counts['pending']}</b>\n"
        f"❌ خارج‌شده از کانال: <b>{counts['left']}</b>\n\n"
        f"🎟 امتیاز: <b>{counts['points']}</b>\n\n{next_text}"
    )


def render_referrals(campaign: Campaign, db: ReferralDB, user_id: int) -> str:
    rows = db.referral_list(campaign, user_id, limit=15)
    if not rows:
        return "<b>👥 دعوت‌های من</b>\n\nهنوز کسی از طریق لینک اختصاصی تو عضو کانال نشده است."
    lines = ["<b>👥 دعوت‌های من</b>\n"]
    for row in rows:
        label = escape(row["first_name"] or ("@" + row["username"] if row["username"] else "کاربر تلگرام"))
        if row["username"] and row["first_name"]:
            label += f" (@{escape(row['username'])})"
        if row["status"] == "qualified":
            status = "✅ تأییدشده"
        elif row["status"] == "left":
            status = "❌ خارج شده"
        else:
            status = f"⏳ {remaining_label(row['remaining_seconds'])} تا تأیید"
        lines.append(f"• {label} — {status}")
    if len(rows) == 15:
        lines.append("\nآخرین ۱۵ دعوت نمایش داده شده است.")
    return "\n".join(lines)


def render_top(campaign: Campaign, db: ReferralDB) -> str:
    rows = db.leaderboard(campaign, limit=10)
    if not rows:
        return "<b>🏆 جدول مسابقه</b>\n\nهنوز کسی امتیاز نگرفته است."
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"<b>🏆 جدول مسابقه — {escape(campaign.name)}</b>\n"]
    for index, row in enumerate(rows):
        badge = medals[index] if index < 3 else f"{index + 1}."
        name = escape(row["first_name"] or ("@" + row["username"] if row["username"] else "کاربر"))
        lines.append(f"{badge} {name} — <b>{row['points']}</b> 🎟 ({row['qualified']} دعوت تأییدشده)")
    return "\n".join(lines)


def render_rules(campaign: Campaign) -> str:
    cap = (f"حداکثر امتیاز قابل استفاده در قرعه‌کشی <b>{campaign.max_points}</b> است."
           if campaign.max_points else "برای امتیازها سقفی تعیین نشده است.")
    return (
        f"<b>📜 قوانین {escape(campaign.name)}</b>\n\n"
        f"1️⃣ لینک اختصاصی خودت را فقط از همین ربات دریافت کن.\n\n"
        f"2️⃣ دوستت باید ابتدا از لینک اختصاصی تو وارد ربات شود و سپس از داخل ربات عضو کانال شود.\n\n"
        f"3️⃣ هر <b>{campaign.invites_per_point}</b> دوست که این مراحل را انجام دهد و حداقل "
        f"<b>{hours_label(campaign.min_stay_hours)}</b> پیوسته عضو بماند، برای تو ۱ امتیاز ایجاد می‌کند.\n\n"
        f"4️⃣ اگر دوستت از کانال خارج شود، برای امتیاز تو حساب نمی‌شود. اگر دوباره عضو شود، زمان انتظار از صفر شروع می‌شود.\n\n"
        f"5️⃣ هر حساب تلگرام در هر مسابقه فقط یک‌بار و برای اولین معرف ثبت‌شده حساب می‌شود.\n\n"
        f"6️⃣ حساب‌های فیک یا تلاش برای دستکاری مسابقه می‌تواند باعث حذف شود.\n\n"
        f"7️⃣ هر امتیاز یک بلیت قرعه‌کشی است و هر نفر حداکثر یک بار می‌تواند برنده شود.\n\n"
        f"8️⃣ قبل از قرعه‌کشی، عضویت دعوت‌شده‌ها و خود شرکت‌کنندگان دوباره بررسی می‌شود.\n\n"
        f"9️⃣ {cap}"
    )


def render_prizes(campaign: Campaign) -> str:
    prize = escape(campaign.prize_text) if campaign.prize_text else "جزئیات جایزه به‌زودی اعلام می‌شود."
    return f"<b>🎁 جوایز — {escape(campaign.name)}</b>\n\n{prize}\n\n🏆 تعداد برندگان: <b>{campaign.num_winners}</b> نفر"
