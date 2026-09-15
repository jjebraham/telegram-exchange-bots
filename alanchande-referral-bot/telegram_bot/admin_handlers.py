from __future__ import annotations

import asyncio
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from referral_core import Campaign, parse_datetime, weighted_draw
from .config import Settings, telegram_membership
from .context import is_admin, services


def denied(update: Update, settings: Settings) -> bool:
    return not is_admin(update, settings)


async def cmd_campaign_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    parts = [part.strip() for part in " ".join(context.args).split("|")]
    if len(parts) != 5:
        await update.message.reply_text(
            "Usage:\n/campaign_create slug | name | start_iso | end_iso | prize\n\n"
            "Example:\n/campaign_create autumn26 | Autumn Giveaway | "
            "2026-09-20T00:00:00+03:00 | 2026-10-20T23:59:59+03:00 | 5 prizes"
        )
        return
    slug, name, start_raw, end_raw, prize = parts
    try:
        campaign = db.create_campaign(
            slug, name, parse_datetime(start_raw), parse_datetime(end_raw), prize,
            invites_per_point=settings.default_invites_per_point,
            min_stay_hours=settings.default_min_stay_hours,
            max_points=settings.default_max_points,
            num_winners=settings.default_num_winners,
        )
    except Exception as exc:
        await update.message.reply_text(f"Could not create campaign: {exc}")
        return
    await update.message.reply_text(
        f"Created draft campaign {campaign.slug}. Activate with /campaign_activate {campaign.slug}"
    )


async def cmd_campaign_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    parts = [part.strip() for part in " ".join(context.args).split("|")]
    if len(parts) != 5:
        await update.message.reply_text(
            "Usage: /campaign_config slug | invites_per_point | min_stay_hours | max_points | winners"
        )
        return
    try:
        campaign = db.configure_campaign(parts[0], *(int(x) for x in parts[1:]))
    except Exception as exc:
        await update.message.reply_text(f"Could not configure campaign: {exc}")
        return
    await update.message.reply_text(
        f"Updated {campaign.slug}: {campaign.invites_per_point} invites/point, "
        f"{campaign.min_stay_hours}h stay, max {campaign.max_points or '∞'} points, "
        f"{campaign.num_winners} winners."
    )


async def cmd_campaign_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /campaign_activate <slug>")
        return
    try:
        campaign = db.activate_campaign(context.args[0])
    except Exception as exc:
        await update.message.reply_text(f"Could not activate campaign: {exc}")
        return
    await update.message.reply_text(
        f"Campaign {campaign.slug} is active. "
        f"Live now: {'yes' if campaign.is_live() else 'no (check start/end times)'}"
    )


async def cmd_campaign_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /campaign_close <slug>")
        return
    try:
        campaign = db.close_campaign(context.args[0])
    except Exception as exc:
        await update.message.reply_text(f"Could not close campaign: {exc}")
        return
    await update.message.reply_text(f"Campaign {campaign.slug} is closed to new referrals.")


async def cmd_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    campaigns = db.list_campaigns()
    if not campaigns:
        await update.message.reply_text("No campaigns yet.")
        return
    lines = ["Campaigns:"]
    for c in campaigns:
        lines.append(f"• {c.slug} — {c.status} — {c.start_dt.isoformat()} → {c.end_dt.isoformat()}")
    await update.message.reply_text("\n".join(lines))


async def cmd_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Campaign not found (or no live campaign).")
        return
    stats = db.admin_stats(campaign)
    await update.message.reply_text(
        f"Stats for {campaign.slug}\nParticipants with links: {stats['participants']}\n"
        f"Referrals total: {stats['referrals_total']}\nActive: {stats['active']}\n"
        f"Qualified: {stats['qualified']}\nPending: {stats['pending']}\nLeft: {stats['left']}\n"
        f"Entrants: {stats['entrants']}\nTickets: {stats['tickets']}"
    )


async def cmd_funnel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /funnel [campaign_slug] — campaign not found.")
        return

    stats = db.funnel_stats(campaign)
    lines = [
        f"📈 Funnel — {campaign.slug}",
        "",
        f"Bot starts tracked: {stats['bot_starts']}",
        f"Participants with personal links: {stats['participants_with_links']}",
        f"Referral deep-link opens tracked: {stats['referral_opens']}",
        f"Unique referral candidates in DB: {stats['referral_candidates']}",
        f"Joined referrals: {stats['joined_referrals']}",
        f"Active referrals now: {stats['active_referrals']}",
        f"Qualified referrals: {stats['qualified_referrals']}",
    ]
    if stats["sources"]:
        lines.extend(["", "Start sources:"])
        lines.extend(f"• {row['source']}: {row['count']}" for row in stats["sources"])
    lines.extend([
        "",
        "Tracking note: bot-start/referral-open events are counted from the deployment of funnel tracking.",
        "Telegram post views and completion of the native Share action are not visible to the bot.",
    ])
    await update.message.reply_text("\n".join(lines))


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /audit <user_id> [campaign_slug]")
        return
    user_id = int(context.args[0])
    campaign = db.get_campaign(context.args[1]) if len(context.args) > 1 else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Campaign not found (or no live campaign).")
        return
    audit = db.audit_user(campaign, user_id)
    counts = audit["counts"]
    lines = [
        f"Audit {user_id} / {campaign.slug}",
        f"Qualified: {counts['qualified']} | Pending: {counts['pending']} | Left: {counts['left']}",
        f"Points: {counts['points']}",
        f"Invite link: {audit['invite_link'] or '(none)'}",
    ]
    if audit["referred_by"]:
        lines.append(
            f"Referred by: {audit['referred_by']['referrer_id']} | "
            f"active={audit['referred_by']['active']} | "
            f"stay_since={audit['referred_by']['stay_since']}"
        )
    await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)


async def verify_campaign(application: Application, campaign: Campaign) -> dict:
    settings: Settings = application.bot_data["settings"]
    db = application.bot_data["db"]
    referral_ids = db.qualified_referral_ids(campaign)
    entrant_ids = db.entrant_user_ids(campaign)
    semaphore = asyncio.Semaphore(8)
    errors, invalid_referrals = [], []
    valid_entrants: set[int] = set()

    async def check(uid: int) -> tuple[int, bool | None]:
        async with semaphore:
            try:
                return uid, await telegram_membership(application.bot, settings, uid)
            except TelegramError:
                return uid, None

    for uid, active in await asyncio.gather(*(check(uid) for uid in referral_ids)):
        if active is None:
            errors.append(uid)
        elif not active:
            invalid_referrals.append(uid)
    if invalid_referrals:
        db.deactivate_referrals(campaign.id, invalid_referrals)
    for uid, active in await asyncio.gather(*(check(uid) for uid in entrant_ids)):
        if active is None:
            errors.append(uid)
        elif active:
            valid_entrants.add(uid)
    return {
        "qualified_checked": len(referral_ids),
        "invalid_referrals": invalid_referrals,
        "entrant_checked": len(entrant_ids),
        "eligible_entrants": valid_entrants,
        "errors": sorted(set(errors)),
    }


async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /verify <campaign_slug>")
        return
    campaign = db.get_campaign(context.args[0])
    if not campaign:
        await update.message.reply_text("Campaign not found.")
        return
    report = await verify_campaign(context.application, campaign)
    if report["errors"]:
        await update.message.reply_text(
            f"Verification incomplete: {len(report['errors'])} Telegram lookups failed. "
            "Do not draw until this is clean."
        )
        return
    await update.message.reply_text(
        f"Verification complete for {campaign.slug}.\n"
        f"Qualified referrals checked: {report['qualified_checked']}\n"
        f"Invalid/left referrals removed: {len(report['invalid_referrals'])}\n"
        f"Entrants checked: {report['entrant_checked']}\n"
        f"Eligible entrants: {len(report['eligible_entrants'])}"
    )


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    parts = [part.strip() for part in " ".join(context.args).split("|", 1)]
    if len(parts) != 2 or not all(parts):
        await update.message.reply_text("Usage: /draw campaign_slug | public_seed")
        return
    slug, seed = parts
    campaign = db.get_campaign(slug)
    if not campaign:
        await update.message.reply_text("Campaign not found.")
        return
    if db.draw_for_campaign(campaign.id):
        await update.message.reply_text("This campaign has already been drawn.")
        return
    if campaign.status == "active" and campaign.is_live():
        await update.message.reply_text(
            "Campaign is still live. Close it with /campaign_close before drawing."
        )
        return
    if campaign.status not in {"closed", "active"}:
        await update.message.reply_text(f"Campaign status {campaign.status!r} is not drawable.")
        return
    await update.message.reply_text("Running final Telegram membership verification…")
    report = await verify_campaign(context.application, campaign)
    if report["errors"]:
        await update.message.reply_text(
            f"Draw aborted: {len(report['errors'])} membership checks failed. "
            "Run /verify again after fixing Telegram/API permissions."
        )
        return
    entrants = db.current_entrants(campaign, eligible_user_ids=report["eligible_entrants"])
    if len(entrants) < campaign.num_winners:
        await update.message.reply_text(
            f"Only {len(entrants)} eligible entrants; need at least {campaign.num_winners}."
        )
        return
    winners = weighted_draw(entrants, seed, campaign.num_winners)
    summary = (
        f"qualified_checked={report['qualified_checked']};"
        f"invalid_referrals={len(report['invalid_referrals'])};"
        f"entrant_checked={report['entrant_checked']};"
        f"eligible_entrants={len(report['eligible_entrants'])}"
    )
    digest = db.save_draw(campaign, seed, entrants, winners, summary)
    lines = [
        f"<b>🎁 Draw complete — {escape(campaign.name)}</b>\n",
        f"Entrants: <b>{len(entrants)}</b>",
        f"Tickets: <b>{sum(t for _, t in entrants)}</b>",
        f"Seed: <code>{escape(seed)}</code>",
        f"Entrant SHA-256: <code>{digest}</code>\n",
        "<b>Winners:</b>",
    ]
    for index, uid in enumerate(winners, 1):
        lines.append(f"{index}. <code>{uid}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
