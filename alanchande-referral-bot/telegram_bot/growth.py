from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import timedelta, timezone
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from referral_core import Campaign, parse_datetime, utcnow
from .context import is_admin, services

log = logging.getLogger("alanchande_referral_bot")
ISTANBUL = timezone(timedelta(hours=3))
IRAN = timezone(timedelta(hours=3, minutes=30))
_SOURCE_RE = re.compile(r"[^a-z0-9_-]+")
_ONBOARDING_EVENTS = {
    "bot_start_new",
    "bot_start_returning",
    "entry_screen_shown",
    "entry_cta_clicked",
    "membership_check_passed",
    "membership_check_failed",
    "membership_check_error",
    "entry_initial_membership_started",
    "entry_initial_membership_passed",
    "entry_initial_membership_failed",
    "entry_initial_membership_error",
    "entry_screen_delivered",
    "entry_cta_membership_started",
    "entry_cta_membership_passed",
    "entry_cta_membership_failed",
    "entry_cta_membership_error",
    "entry_link_created",
    "entry_link_creation_error",
    "referral_welcome_sent",
    "referral_link_included",
    "referral_share_prompt_sent",
    "referral_welcome_error",
    "referral_link_creation_error",
}


def normalize_promo_source(raw: str) -> str:
    source = _SOURCE_RE.sub("_", (raw or "").strip().lower()).strip("_-")
    return source[:48] or "promo"


def canonical_promo_source(raw: str) -> str:
    """Collapse accidental double A/B suffixes from historical promo links."""
    source = normalize_promo_source(raw)
    parts = source.rsplit("_", 2)
    if (
        len(parts) == 3
        and parts[-2] in {"a", "b"}
        and parts[-1] in {"a", "b"}
    ):
        return f"{parts[0]}_{parts[-1]}"
    return source


def promo_source_with_variant(source: str, variant: str | None = None) -> str:
    base = canonical_promo_source(source)
    chosen = (variant or "").strip().lower()

    if chosen in {"a", "b"}:
        # Replace an existing terminal A/B variant instead of appending
        # another one. This prevents mainchannel_b_b, mainchannel_a_b, etc.
        if base.endswith(("_a", "_b")):
            base = base[:-2]

        suffix = f"_{chosen}"
        base = base[: 64 - len(suffix)]
        return base + suffix

    return base[:64]


def promo_variant(source: str) -> str:
    value = (source or "").lower()
    if value.endswith("_a") or value.endswith("-a"):
        return "a"
    if value.endswith("_b") or value.endswith("-b"):
        return "b"
    return "default"


def remaining_text(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "کمتر از یک ساعت"
    hours = max(1, math.ceil(seconds / 3600))
    days, rem = divmod(hours, 24)
    if days and rem:
        return f"{days} روز و {rem} ساعت"
    if days:
        return f"{days} روز"
    return f"{hours} ساعت"


def qualification_cutoff_text(campaign: Campaign) -> str:
    cutoff_ist = campaign.final_qualification_cutoff.astimezone(ISTANBUL)
    cutoff_ir = campaign.final_qualification_cutoff.astimezone(IRAN)
    return (
        f"{cutoff_ist:%Y/%m/%d} {cutoff_ist:%H:%M} استانبول / "
        f"{cutoff_ir:%Y/%m/%d} {cutoff_ir:%H:%M} ایران"
    )


async def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username
    if not username:
        raise RuntimeError("bot username is unavailable")
    return username


def build_promo_link(username: str, source: str, variant: str | None = None) -> str:
    src = promo_source_with_variant(source, variant)
    return f"https://t.me/{username}?start=promo_{src}"


def _first_touch_sources(db, campaign_id: int) -> tuple[dict[int, str], str | None]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT user_id,source,created_at FROM funnel_events
               WHERE campaign_id=? AND event_type='bot_start'
               ORDER BY created_at ASC, user_id ASC, source ASC""",
            (campaign_id,),
        ).fetchall()
    first: dict[int, str] = {}
    tracking_started = None
    for row in rows:
        if tracking_started is None:
            tracking_started = str(row["created_at"])
        first.setdefault(
            int(row["user_id"]),
            canonical_promo_source(str(row["source"] or "organic")),
        )
    return first, tracking_started


def _onboarding_event_users(db, campaign_id: int) -> dict[str, dict[str, set[int]]]:
    placeholders = ",".join("?" for _ in _ONBOARDING_EVENTS)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT user_id,event_type,source FROM funnel_events
                WHERE campaign_id=? AND event_type IN ({placeholders})""",
            (campaign_id, *sorted(_ONBOARDING_EVENTS)),
        ).fetchall()
    result: dict[str, dict[str, set[int]]] = {}
    for row in rows:
        source = canonical_promo_source(str(row["source"] or "organic"))
        event_type = str(row["event_type"])
        result.setdefault(source, {}).setdefault(event_type, set()).add(int(row["user_id"]))
    return result


def source_performance(db, campaign: Campaign) -> dict:
    """First-touch source attribution plus post-deploy onboarding instrumentation."""
    first_source, tracking_started = _first_touch_sources(db, campaign.id)
    onboarding = _onboarding_event_users(db, campaign.id)
    cutoff = campaign.cutoff(utcnow())
    with db.connect() as conn:
        entered = {
            int(row["user_id"])
            for row in conn.execute(
                """SELECT DISTINCT user_id FROM funnel_events
                   WHERE campaign_id=? AND event_type='entered_contest'""",
                (campaign.id,),
            ).fetchall()
        }
        link_rows = conn.execute(
            """SELECT user_id,created_at FROM invite_links
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()
        links = {int(row["user_id"]) for row in link_rows}
        link_created_at = {
            int(row["user_id"]): str(row["created_at"])
            for row in link_rows
        }
        open_users = {
            int(row["user_id"])
            for row in conn.execute(
                """SELECT DISTINCT user_id FROM funnel_events
                   WHERE campaign_id=? AND event_type='referral_open'""",
                (campaign.id,),
            ).fetchall()
        }
        pending = conn.execute(
            """SELECT joined_user_id,referrer_id FROM pending_referrals
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()
        refs = conn.execute(
            """SELECT joined_user_id,referrer_id,active,stay_since FROM referrals
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()

    tracking_started_dt = (
        parse_datetime(tracking_started)
        if tracking_started
        else None
    )

    def holder_source(user_id: int) -> str:
        created_at = link_created_at.get(user_id)

        if tracking_started_dt is not None and created_at is not None:
            if parse_datetime(created_at) < tracking_started_dt:
                return "legacy/untracked"

        return first_source.get(user_id, "legacy/untracked")

    buckets: dict[str, dict] = {}

    def bucket(source: str) -> dict:
        return buckets.setdefault(source, {
            "source": source,
            "starts": 0,
            "entered": 0,
            "links": 0,
            "referral_opens": 0,
            "candidates": 0,
            "joins": 0,
            "active": 0,
            "qualified": 0,
            "new_starts": 0,
            "returning_starts": 0,
            "unclassified_starts": 0,
            "new_entered": 0,
            "entry_shown": 0,
            "entry_cta": 0,
            "membership_passed": 0,
            "membership_failed": 0,
            "membership_error": 0,
            "initial_member_passed": 0,
            "initial_member_failed": 0,
            "initial_member_error": 0,
            "screen_delivered": 0,
            "cta_member_passed": 0,
            "cta_member_failed": 0,
            "cta_member_error": 0,
            "entry_link_created": 0,
            "entry_link_error": 0,
            "referral_welcome_sent": 0,
            "referral_link_included": 0,
            "referral_share_prompt_sent": 0,
            "referral_welcome_error": 0,
            "referral_link_creation_error": 0,
        })

    for uid, source in first_source.items():
        item = bucket(source)
        item["starts"] += 1
        if uid in entered:
            item["entered"] += 1

    # Count every personal-link holder, including participants whose link
    # predates analytics and who never generated a tracked bot_start.
    for uid in links:
        bucket(holder_source(uid))["links"] += 1

    for source, events in onboarding.items():
        item = bucket(source)
        new_users = events.get("bot_start_new", set())
        returning_users = events.get("bot_start_returning", set())
        item["new_starts"] = len(new_users)
        item["returning_starts"] = len(returning_users)
        item["new_entered"] = len(new_users & entered)
        item["entry_shown"] = len(events.get("entry_screen_shown", set()))
        item["entry_cta"] = len(events.get("entry_cta_clicked", set()))
        item["membership_passed"] = len(events.get("membership_check_passed", set()))
        item["membership_failed"] = len(events.get("membership_check_failed", set()))
        item["membership_error"] = len(events.get("membership_check_error", set()))
        item["initial_member_passed"] = len(events.get("entry_initial_membership_passed", set()))
        item["initial_member_failed"] = len(events.get("entry_initial_membership_failed", set()))
        item["initial_member_error"] = len(events.get("entry_initial_membership_error", set()))
        item["screen_delivered"] = len(events.get("entry_screen_delivered", set()))
        item["cta_member_passed"] = len(events.get("entry_cta_membership_passed", set()))
        item["cta_member_failed"] = len(events.get("entry_cta_membership_failed", set()))
        item["cta_member_error"] = len(events.get("entry_cta_membership_error", set()))
        item["entry_link_created"] = len(events.get("entry_link_created", set()))
        item["entry_link_error"] = len(events.get("entry_link_creation_error", set()))
        item["referral_welcome_sent"] = len(events.get("referral_welcome_sent", set()))
        item["referral_link_included"] = len(events.get("referral_link_included", set()))
        item["referral_share_prompt_sent"] = len(events.get("referral_share_prompt_sent", set()))
        item["referral_welcome_error"] = len(events.get("referral_welcome_error", set()))
        item["referral_link_creation_error"] = len(
            events.get("referral_link_creation_error", set())
        )

    candidate_seen: set[int] = set()
    for row in list(pending) + list(refs):
        joined_uid = int(row["joined_user_id"])
        referrer_id = int(row["referrer_id"])
        source = holder_source(referrer_id)
        item = bucket(source)
        if joined_uid not in candidate_seen:
            item["candidates"] += 1
            if joined_uid in open_users:
                item["referral_opens"] += 1
            candidate_seen.add(joined_uid)

    for row in refs:
        referrer_id = int(row["referrer_id"])
        source = holder_source(referrer_id)
        item = bucket(source)
        item["joins"] += 1
        if int(row["active"]):
            item["active"] += 1
            if parse_datetime(row["stay_since"]) <= cutoff:
                item["qualified"] += 1

    for item in buckets.values():
        classified = item["new_starts"] + item["returning_starts"]
        item["unclassified_starts"] = max(0, item["starts"] - classified)
        item["start_to_entered_pct"] = (
            round(item["entered"] * 100.0 / item["starts"], 1) if item["starts"] else None
        )
        item["start_to_link_pct"] = (
            round(item["links"] * 100.0 / item["starts"], 1) if item["starts"] else None
        )
        item["new_start_to_entered_pct"] = (
            round(item["new_entered"] * 100.0 / item["new_starts"], 1)
            if item["new_starts"] else None
        )
        item["entry_cta_pct"] = (
            round(item["entry_cta"] * 100.0 / item["entry_shown"], 1)
            if item["entry_shown"] else None
        )
        item["candidate_to_join_pct"] = (
            round(item["joins"] * 100.0 / item["candidates"], 1) if item["candidates"] else None
        )
        item["join_to_active_pct"] = (
            round(item["active"] * 100.0 / item["joins"], 1) if item["joins"] else None
        )

    rows = sorted(
        buckets.values(),
        key=lambda row: (
            row["source"] == "legacy/untracked",
            -row["starts"],
            -row["joins"],
            row["source"],
        ),
    )
    return {"tracking_started_at": tracking_started, "rows": rows}


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _masked_name(row: dict) -> str:
    raw = str(row.get("first_name") or row.get("username") or "").strip()
    if raw:
        return escape(raw[:2] + "***")
    return "کاربر ***" + str(row["user_id"])[-3:]


def weekly_post_text(db, campaign: Campaign, promo_link: str) -> str:
    stats = db.admin_stats(campaign)
    top = db.leaderboard(campaign, limit=5)
    left = remaining_text((campaign.end_dt - utcnow()).total_seconds())
    lines = [
        f"🎁 <b>گزارش مسابقه {escape(campaign.name)}</b>",
        "",
        f"👥 شرکت‌کننده‌ها: <b>{stats['participants']}</b>",
        f"🔥 دعوت‌های فعال: <b>{stats['active']}</b>",
        f"🎟 دعوت‌های تأییدشده: <b>{stats['qualified']}</b>",
        f"⏳ <b>{left}</b> تا پایان ثبت دعوت‌ها",
        f"⚠️ آخرین زمان ورود دعوت جدید برای بلیت نهایی: <b>{qualification_cutoff_text(campaign)}</b>",
        "",
    ]
    if top:
        lines.append("🏆 <b>نفرات برتر فعلی:</b>")
        for index, row in enumerate(top, 1):
            lines.append(
                f"{index}. {_masked_name(row)} — ⭐ {row['current_points']} موقت | "
                f"🎟 {row['confirmed_points']} تأییدشده"
            )
        lines.append("")
    lines.extend([
        "ℹ️ جدول فقط روند فعلی را نشان می‌دهد؛ برنده‌ها با قرعه‌کشی وزن‌دار از بین بلیت‌های تأییدشده انتخاب می‌شوند.",
        "",
        f"🎁 <b>جوایز:</b> {escape(campaign.prize_text)}",
        "",
        "👇 برای شرکت و گرفتن لینک اختصاصی، دکمه زیر را بزن:",
        promo_link,
        "",
        "📢 @alanchande_com",
    ])
    return "\n".join(lines)


def promo_post_text(campaign: Campaign, promo_link: str, variant: str) -> str:
    left = remaining_text((campaign.end_dt - utcnow()).total_seconds())
    cutoff = qualification_cutoff_text(campaign)

    if variant == "b":
        return (
            f"🎁 <b>{escape(campaign.name)} — جایزه نقدی</b>\n\n"
            f"🏆 <b>{campaign.num_winners} برنده</b>\n"
            f"💰 {escape(campaign.prize_text)}\n\n"
            "✅ اعضای فعلی کانال هم می‌تونن شرکت کنن.\n"
            f"👥 هر <b>{campaign.invites_per_point} دوست</b> که با لینک تو عضو بشن = ۱ امتیاز\n"
            "🎟 بعد از تکمیل مدت عضویت، امتیازت برای قرعه‌کشی نهایی تأیید میشه.\n\n"
            "🔐 قوانین مسابقه بعد از شروع تغییر نمی‌کنه.\n"
            "🎲 قرعه‌کشی شفاف و قابل بررسی انجام میشه.\n\n"
            f"⚠️ آخرین زمان ورود دعوت جدید برای بلیت نهایی: <b>{cutoff}</b>\n"
            f"⏳ {left} تا پایان ثبت دعوت‌ها\n\n"
            "👇 <b>برای شرکت فقط دکمه زیر رو بزن</b>"
        )

    body = (
        f"🎁 <b>{escape(campaign.name)} — جایزه نقدی</b>\n\n"
        f"🏆 <b>{campaign.num_winners} برنده</b>\n"
        f"💰 {escape(campaign.prize_text)}\n\n"
        "✅ اعضای فعلی کانال هم می‌تونن شرکت کنن.\n"
        "فقط وارد ربات شو، لینک اختصاصی خودت را بگیر و برای دوستات بفرست.\n"
        f"⭐ هر {campaign.invites_per_point} دعوت فعال = ۱ امتیاز موقت\n\n"
        "🔐 قوانین مسابقه بعد از شروع تغییر نمی‌کنه.\n"
        f"⚠️ آخرین زمان ورود دعوت جدید برای بلیت نهایی: <b>{cutoff}</b>\n"
        f"⏳ {left} تا پایان ثبت دعوت‌ها"
    )
    return body + f"\n\n👇 شرکت در مسابقه:\n{promo_link}"


async def cmd_promo_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    if not context.args:
        await update.message.reply_text("Usage: /promo_link <source> [a|b]")
        return
    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text("No live campaign.")
        return
    source = normalize_promo_source(context.args[0])
    variant = context.args[1].lower() if len(context.args) > 1 else ""
    if variant and variant not in {"a", "b"}:
        await update.message.reply_text("Variant must be a or b.")
        return
    username = await _bot_username(context)
    link = build_promo_link(username, source, variant or None)
    lines = [
        f"🔗 Promo link — {campaign.slug}",
        f"Source: {promo_source_with_variant(source, variant or None)}",
        link,
    ]
    if not variant:
        lines.extend([
            "",
            "A/B alternatives:",
            f"A: {build_promo_link(username, source, 'a')}",
            f"B: {build_promo_link(username, source, 'b')}",
        ])
    await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /sources [campaign_slug]")
        return
    report = source_performance(db, campaign)
    lines = [f"📡 Source performance — {campaign.slug}"]
    if report["tracking_started_at"]:
        lines.append(f"Tracked from: {report['tracking_started_at']}")
    lines.append("")
    if not report["rows"]:
        lines.append("No source data yet.")
    for row in report["rows"][:20]:
        lines.extend([
            f"• {row['source']}",
            f"  starts={row['starts']} entered={row['entered']} links={row['links']} "
            f"opens={row['referral_opens']} candidates={row['candidates']}",
            f"  joins={row['joins']} active={row['active']} qualified={row['qualified']}",
            f"  classified starts: new={row['new_starts']} returning={row['returning_starts']} "
            f"unclassified={row['unclassified_starts']}",
            f"  onboarding: shown={row['entry_shown']} cta={row['entry_cta']} "
            f"member_ok={row['membership_passed']} member_no={row['membership_failed']} "
            f"errors={row['membership_error']}",
            f"  detailed: delivered={row['screen_delivered']} "
            f"initial_ok={row['initial_member_passed']} initial_no={row['initial_member_failed']} "
            f"cta_ok={row['cta_member_passed']} cta_no={row['cta_member_failed']} "
            f"link_ok={row['entry_link_created']} link_err={row['entry_link_error']}",
            f"  referral path: welcome={row['referral_welcome_sent']} "
            f"link={row['referral_link_included']} prompt={row['referral_share_prompt_sent']} "
            f"welcome_err={row['referral_welcome_error']} "
            f"link_err={row['referral_link_creation_error']}",
            f"  start→enter={_pct(row['start_to_entered_pct'])} | "
            f"new start→enter={_pct(row['new_start_to_entered_pct'])} | "
            f"shown→cta={_pct(row['entry_cta_pct'])} | candidate→join={_pct(row['candidate_to_join_pct'])}",
        ])
    lines.append("\nclassified starts are available only after this onboarding instrumentation was deployed.")
    lines.append("legacy/untracked = activity whose referrer predates first-touch source tracking.")
    await update.message.reply_text("\n".join(lines))


async def cmd_funnel_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /funnel [campaign_slug]")
        return

    stats = db.funnel_stats(campaign)
    report = source_performance(db, campaign)
    tracked = [row for row in report["rows"] if row["source"] != "legacy/untracked"]
    legacy = next((row for row in report["rows"] if row["source"] == "legacy/untracked"), None)
    tracked_links = sum(row["links"] for row in tracked)
    tracked_candidates = sum(row["candidates"] for row in tracked)
    tracked_joins = sum(row["joins"] for row in tracked)
    tracked_active = sum(row["active"] for row in tracked)
    tracked_qualified = sum(row["qualified"] for row in tracked)
    new_starts = sum(row["new_starts"] for row in tracked)
    returning_starts = sum(row["returning_starts"] for row in tracked)
    new_entered = sum(row["new_entered"] for row in tracked)
    new_start_to_enter = round(new_entered * 100.0 / new_starts, 1) if new_starts else None
    start_to_enter = (
        round(stats["entered_contest"] * 100.0 / stats["bot_starts"], 1)
        if stats["bot_starts"] else None
    )

    lines = [f"📈 Funnel — {campaign.slug}", ""]
    lines.append("📡 Tracked since analytics instrumentation")
    lines.append(f"Tracking began: {report['tracking_started_at'] or 'no tracked start yet'}")
    lines.extend([
        f"• bot starts: {stats['bot_starts']}",
        f"• classified new starts: {new_starts}",
        f"• classified returning starts: {returning_starts}",
        f"• new-start → entered: {_pct(new_start_to_enter)}",
        f"• entered contest events: {stats['entered_contest']} ({_pct(start_to_enter)} of starts)",
        f"• referral-link opens: {stats['referral_opens']}",
        f"• tracked-source participants with links: {tracked_links}",
        f"• tracked-source referral candidates: {tracked_candidates}",
        f"• tracked-source joined referrals: {tracked_joins}",
        f"• tracked-source active referrals: {tracked_active}",
        f"• tracked-source qualified referrals: {tracked_qualified}",
        "",
        "📚 All-time database totals",
        f"• participants with personal links: {stats['participants_with_links']}",
        f"• unique referral candidates: {stats['referral_candidates']}",
        f"• joined referrals: {stats['joined_referrals']}",
        f"• active referrals now: {stats['active_referrals']}",
        f"• qualified referrals now: {stats['qualified_referrals']}",
    ])
    if legacy:
        lines.extend([
            "",
            "🕰 Legacy/untracked downstream activity",
            f"• candidates={legacy['candidates']} joins={legacy['joins']} active={legacy['active']} qualified={legacy['qualified']}",
        ])
    lines.extend([
        "",
        "Use /sources for first-touch source, new-vs-returning starts and onboarding steps.",
        "Historical DB totals can be larger than tracked starts because analytics was deployed after the campaign began.",
        "Telegram post views and native Share completion are not visible to the bot.",
    ])
    await update.message.reply_text("\n".join(lines))


async def cmd_promo_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.live_campaign()
    if not campaign:
        await update.message.reply_text("No live campaign.")
        return
    source = normalize_promo_source(context.args[0] if context.args else "promo_post")
    variant_arg = context.args[1].lower() if len(context.args) > 1 else "a"
    if variant_arg not in {"a", "b"}:
        await update.message.reply_text("Usage: /promo_post <source> [a|b]")
        return
    username = await _bot_username(context)
    link = build_promo_link(username, source, variant_arg)
    await update.message.reply_text(
        promo_post_text(campaign, link, variant_arg),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 شرکت در مسابقه", url=link)],
            [InlineKeyboardButton("📢 کانال الان چنده؟", url=settings.channel_url)],
        ]),
        disable_web_page_preview=True,
    )


async def cmd_weekly_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /weekly_post [campaign_slug] [source]")
        return
    source = normalize_promo_source(context.args[1] if len(context.args) > 1 else "weekly")
    username = await _bot_username(context)
    link = build_promo_link(username, source)
    await update.message.reply_text(
        weekly_post_text(db, campaign, link),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 شرکت در مسابقه", url=link)],
            [InlineKeyboardButton("📢 کانال الان چنده؟", url=settings.channel_url)],
        ]),
        disable_web_page_preview=True,
    )


def _digest_marker(campaign_id: int, admin_id: int, date_key: str) -> str:
    return f"daily_digest:{campaign_id}:{admin_id}:{date_key}"


def _digest_sent(db, campaign_id: int, admin_id: int, date_key: str) -> bool:
    name = _digest_marker(campaign_id, admin_id, date_key)
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM maintenance_status WHERE name=?", (name,)).fetchone() is not None


def _mark_digest_sent(db, campaign_id: int, admin_id: int, date_key: str) -> None:
    db.set_maintenance_status(_digest_marker(campaign_id, admin_id, date_key), True, {"date": date_key})


def daily_digest_text(db, campaign: Campaign) -> str:
    today = db.capture_daily_metrics(campaign)
    history = db.daily_metrics(campaign.id, limit=2)
    previous = history[1] if len(history) > 1 else None
    dp = int(today["participants"]) - int(previous["participants"]) if previous else 0
    dj = int(today["joined"]) - int(previous["joined"]) if previous else 0
    da = int(today["active"]) - int(previous["active"]) if previous else 0
    report = source_performance(db, campaign)
    tracked = [row for row in report["rows"] if row["source"] != "legacy/untracked"]
    winner = max(tracked, key=lambda row: (row["joins"], row["links"], row["starts"]), default=None)
    flags = len(db.fraud_flags(campaign))
    lines = [
        f"📊 <b>گزارش روزانه {escape(campaign.name)}</b>",
        "",
        f"👥 شرکت‌کننده‌ها: <b>{today['participants']}</b> ({dp:+d} نسبت به snapshot قبلی)",
        f"🤝 دعوت‌های ثبت‌شده: <b>{today['joined']}</b> ({dj:+d})",
        f"🔥 فعال: <b>{today['active']}</b> ({da:+d})",
        f"🎟 تأییدشده: <b>{today['qualified']}</b>",
        f"🎫 بلیت‌ها: <b>{today['tickets']}</b>",
        f"🧬 K proxy: <b>{today['k_factor_proxy']}</b>",
    ]
    if winner:
        lines.append(
            f"🏅 بهترین منبع tracked فعلی: <b>{escape(winner['source'])}</b> "
            f"(starts={winner['starts']}, joins={winner['joins']})"
        )
    else:
        lines.append("🏅 بهترین منبع tracked فعلی: داده کافی نیست")
    lines.append(f"⚠️ سیگنال‌های بررسی تقلب: <b>{flags}</b>")
    return "\n".join(lines)


async def daily_admin_digest_pass(application: Application) -> dict:
    settings = application.bot_data["settings"]
    db = application.bot_data["db"]
    campaign = db.live_campaign()
    if not campaign:
        return {"campaign": None, "sent": 0}
    local_now = utcnow().astimezone(ISTANBUL)
    digest_hour = int(getattr(settings, "daily_digest_hour_istanbul", 21))
    if local_now.hour < digest_hour:
        return {"campaign": campaign.slug, "sent": 0, "waiting_for_hour": digest_hour}
    date_key = local_now.date().isoformat()
    text = daily_digest_text(db, campaign)
    sent = 0
    for admin_id in sorted(settings.admin_ids):
        if _digest_sent(db, campaign.id, admin_id, date_key):
            continue
        try:
            await application.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            _mark_digest_sent(db, campaign.id, admin_id, date_key)
            sent += 1
        except (Forbidden, BadRequest):
            log.warning("Daily digest unreachable admin=%s", admin_id)
        except TelegramError:
            log.exception("Daily digest failed admin=%s", admin_id)
    return {"campaign": campaign.slug, "sent": sent, "date": date_key}


async def daily_admin_digest_loop(application: Application) -> None:
    settings = application.bot_data["settings"]
    db = application.bot_data["db"]
    while True:
        try:
            details = await daily_admin_digest_pass(application)
            db.set_maintenance_status("daily_admin_digest", True, details)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db.set_maintenance_status("daily_admin_digest", False, error=str(exc))
            log.exception("Daily admin digest worker failed")
        await asyncio.sleep(max(900, int(getattr(settings, "daily_digest_check_seconds", 3600))))
