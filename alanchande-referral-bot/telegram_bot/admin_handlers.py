from __future__ import annotations

import asyncio
import hashlib
import json
from html import escape

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError
from telegram.ext import Application, ContextTypes

from referral_core import Campaign, parse_datetime, utcnow, weighted_draw
from .config import Settings, telegram_membership
from .context import is_admin, services


def denied(update: Update, settings: Settings) -> bool:
    return not is_admin(update, settings)


def admin_id(update: Update) -> int:
    return int(update.effective_user.id) if update.effective_user else 0


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
        db.log_admin_action(campaign.id, admin_id(update), "campaign_create", {
            "slug": campaign.slug, "start_at": campaign.start_at,
            "end_at": campaign.end_at, "draw_at": campaign.draw_at,
        })
    except Exception as exc:
        await update.message.reply_text(f"Could not create campaign: {exc}")
        return
    await update.message.reply_text(
        f"Created draft campaign {campaign.slug}.\n"
        f"Draw at: {campaign.draw_dt.isoformat()}\n"
        f"Activate with /campaign_activate {campaign.slug}"
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
    before = db.get_campaign(parts[0])
    try:
        campaign = db.configure_campaign(parts[0], *(int(x) for x in parts[1:]))
    except Exception as exc:
        await update.message.reply_text(f"Could not configure campaign: {exc}")
        return
    db.log_admin_action(campaign.id, admin_id(update), "campaign_config", {
        "before": {
            "invites_per_point": before.invites_per_point if before else None,
            "min_stay_hours": before.min_stay_hours if before else None,
            "max_points": before.max_points if before else None,
            "num_winners": before.num_winners if before else None,
        },
        "after": {
            "invites_per_point": campaign.invites_per_point,
            "min_stay_hours": campaign.min_stay_hours,
            "max_points": campaign.max_points,
            "num_winners": campaign.num_winners,
        },
    })
    await update.message.reply_text(
        f"Updated {campaign.slug}: {campaign.invites_per_point} invites/point, "
        f"{campaign.min_stay_hours}h stay, max {campaign.max_points or '∞'} points, "
        f"{campaign.num_winners} winners."
    )


async def cmd_campaign_draw_at(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    parts = [part.strip() for part in " ".join(context.args).split("|")]
    if len(parts) != 2:
        await update.message.reply_text("Usage: /campaign_draw_at slug | 2026-10-16T21:00:00+03:00")
        return
    try:
        campaign = db.set_campaign_draw_at(parts[0], parse_datetime(parts[1]))
        db.log_admin_action(campaign.id, admin_id(update), "campaign_draw_at", {"draw_at": campaign.draw_at})
    except Exception as exc:
        await update.message.reply_text(f"Could not set draw time: {exc}")
        return
    await update.message.reply_text(f"Draw time for {campaign.slug}: {campaign.draw_dt.isoformat()}")


async def cmd_campaign_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /campaign_activate <slug>")
        return
    try:
        campaign = db.activate_campaign(context.args[0])
        db.log_admin_action(campaign.id, admin_id(update), "campaign_activate", {
            "rules_locked_at": campaign.rules_locked_at,
            "rules_version": campaign.rules_version,
        })
    except Exception as exc:
        await update.message.reply_text(f"Could not activate campaign: {exc}")
        return
    await update.message.reply_text(
        f"Campaign {campaign.slug} is active. Rules are now locked. "
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
        db.log_admin_action(campaign.id, admin_id(update), "campaign_close")
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
        lines.append(
            f"• {c.slug} — {c.status} — {c.start_dt.isoformat()} → {c.end_dt.isoformat()} "
            f"— draw {c.draw_dt.isoformat()} — rules v{c.rules_version}"
        )
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
        f"Qualified now: {stats['qualified']}\nPending: {stats['pending']}\nLeft: {stats['left']}\n"
        f"Confirmed entrants now: {stats['entrants']}\nConfirmed tickets now: {stats['tickets']}\n"
        f"Fixed draw time: {campaign.draw_dt.isoformat()}\n"
        f"Final stay_since cutoff: {campaign.final_qualification_cutoff.isoformat()}"
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
        f"📈 Funnel — {campaign.slug}", "",
        f"Bot starts tracked: {stats['bot_starts']}",
        f"Entered contest tracked: {stats['entered_contest']}",
        f"Participants with personal links: {stats['participants_with_links']}",
        f"Referral deep-link opens tracked: {stats['referral_opens']}",
        f"Unique referral candidates in DB: {stats['referral_candidates']}",
        f"Joined referrals: {stats['joined_referrals']}",
        f"Active referrals now: {stats['active_referrals']}",
        f"Qualified referrals now: {stats['qualified_referrals']}",
    ]
    if stats["sources"]:
        lines.extend(["", "Start sources:"])
        lines.extend(f"• {row['source']}: {row['count']}" for row in stats["sources"])
    lines.extend([
        "", "Historical event tracking starts from the deployment of each event type.",
        "Telegram post views and native Share completion are not visible to the bot.",
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
        f"Active: {counts['active']} | Qualified: {counts['qualified']} | Pending: {counts['pending']} | Left: {counts['left']}",
        f"Current points: {counts['current_points']} | Confirmed tickets: {counts['confirmed_points']}",
        f"Invite link: {audit['invite_link'] or '(none)'}",
    ]
    if audit["referred_by"]:
        lines.append(
            f"Referred by: {audit['referred_by']['referrer_id']} | "
            f"active={audit['referred_by']['active']} | "
            f"stay_since={audit['referred_by']['stay_since']}"
        )
    await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)


async def cmd_flags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        await update.message.reply_text("Usage: /flags [campaign_slug]")
        return
    rows = db.fraud_flags(campaign)
    if not rows:
        await update.message.reply_text(f"No heuristic flags for {campaign.slug}. This is not a guarantee of no fraud.")
        return
    lines = [f"⚠️ Flag-only review — {campaign.slug}", "Never auto-DQ from this report alone.", ""]
    for row in rows[:30]:
        lines.append(
            f"• {row['referrer_id']} — refs={row['referrals']} active={row['active']} — "
            + ", ".join(row["reasons"])
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_adminlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    campaign = db.get_campaign(context.args[0]) if context.args else None
    if context.args and not campaign:
        await update.message.reply_text("Campaign not found.")
        return
    rows = db.admin_actions(campaign.id if campaign else None, limit=20)
    if not rows:
        await update.message.reply_text("No admin audit entries yet.")
        return
    lines = ["🧾 Admin audit log"]
    for row in rows:
        lines.append(
            f"• {row['created_at']} admin={row['admin_user_id']} action={row['action']} campaign={row['campaign_id']}"
        )
    await update.message.reply_text("\n".join(lines))


async def _membership_check(application: Application, settings: Settings, uid: int) -> bool | None:
    for attempt in range(3):
        try:
            return await telegram_membership(application.bot, settings, uid)
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.2)
        except BadRequest as exc:
            text = str(exc).lower()
            if any(marker in text for marker in ("user not found", "user_id_invalid", "participant_id_invalid")):
                return False
            return None
        except TelegramError:
            if attempt == 2:
                return None
            await asyncio.sleep(1.5 * (attempt + 1))
    return None


async def verify_campaign(application: Application, campaign: Campaign,
                          reference_time=None) -> dict:
    settings: Settings = application.bot_data["settings"]
    db = application.bot_data["db"]
    referral_ids = db.qualified_referral_ids(campaign, now=reference_time)
    entrant_ids = [uid for uid, _ in db.confirmed_entrants(campaign, at=reference_time)]
    semaphore = asyncio.Semaphore(6)
    errors, invalid_referrals = [], []
    valid_entrants: set[int] = set()

    async def check(uid: int) -> tuple[int, bool | None]:
        async with semaphore:
            result = await _membership_check(application, settings, uid)
            await asyncio.sleep(0.03)
            return uid, result

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
    db.log_admin_action(campaign.id, admin_id(update), "verify", {
        "qualified_checked": report["qualified_checked"],
        "invalid_referrals": len(report["invalid_referrals"]),
        "entrant_checked": report["entrant_checked"],
        "eligible_entrants": len(report["eligible_entrants"]),
        "errors": report["errors"],
    })
    if report["errors"]:
        await update.message.reply_text(
            f"Verification incomplete: {len(report['errors'])} transient/systemic lookups failed. "
            "Do not snapshot/draw until this is clean."
        )
        return
    await update.message.reply_text(
        f"Verification complete for {campaign.slug}.\n"
        f"Qualified referrals checked: {report['qualified_checked']}\n"
        f"Invalid/deleted/left referrals removed: {len(report['invalid_referrals'])}\n"
        f"Entrants checked: {report['entrant_checked']}\n"
        f"Eligible entrants: {len(report['eligible_entrants'])}"
    )


async def cmd_snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Freeze the verified entrant list before any Bitcoin entropy exists."""
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /snapshot <campaign_slug>")
        return
    campaign = db.get_campaign(context.args[0])
    if not campaign:
        await update.message.reply_text("Campaign not found.")
        return
    if utcnow() < campaign.draw_dt:
        await update.message.reply_text(
            f"Too early. Snapshot is allowed at/after fixed draw time: {campaign.draw_dt.isoformat()}"
        )
        return
    if campaign.is_live():
        await update.message.reply_text("Campaign is still live; wait for the fixed campaign end/draw time.")
        return
    if db.draw_for_campaign(campaign.id):
        await update.message.reply_text("Campaign has already been drawn.")
        return

    await update.message.reply_text("Running fixed-cutoff verification and freezing entrant snapshot…")
    report = await verify_campaign(context.application, campaign, reference_time=campaign.draw_dt)
    if report["errors"]:
        await update.message.reply_text(
            f"Snapshot aborted: {len(report['errors'])} Telegram lookups failed. Retry later."
        )
        return
    entrants = db.confirmed_entrants(
        campaign, at=campaign.draw_dt, eligible_user_ids=report["eligible_entrants"]
    )
    if len(entrants) < campaign.num_winners:
        await update.message.reply_text(
            f"Only {len(entrants)} eligible entrants; need at least {campaign.num_winners}."
        )
        return
    summary = (
        f"qualified_checked={report['qualified_checked']};"
        f"invalid_referrals={len(report['invalid_referrals'])};"
        f"entrant_checked={report['entrant_checked']};"
        f"eligible_entrants={len(report['eligible_entrants'])};"
        f"reference_time={campaign.draw_dt.isoformat()}"
    )
    digest = db.save_draw_snapshot(campaign, entrants, summary)
    snap = db.draw_snapshot(campaign.id)
    db.log_admin_action(campaign.id, admin_id(update), "draw_snapshot", {
        "digest": digest, "entrants": len(entrants), "tickets": sum(t for _, t in entrants),
    })
    await update.message.reply_text(
        f"🔐 Snapshot frozen for {campaign.slug}.\n"
        f"Entrants: {len(entrants)}\nTickets: {sum(t for _, t in entrants)}\n"
        f"SHA-256: {digest}\nSnapshot time: {snap['created_at']}\n\n"
        "Publish this digest now. The draw seed must be the FIRST Bitcoin block after this snapshot time."
    )


async def _verify_first_bitcoin_block(height: int, block_hash: str, snapshot_time) -> dict:
    base = "https://blockstream.info/api"
    block_hash = block_hash.lower().strip()
    if len(block_hash) != 64 or any(ch not in "0123456789abcdef" for ch in block_hash):
        raise ValueError("Bitcoin block hash must be 64 hex characters")
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{base}/block-height/{height}")
        r.raise_for_status()
        canonical = r.text.strip().lower()
        if canonical != block_hash:
            raise ValueError("hash does not match the supplied Bitcoin block height")
        r = await client.get(f"{base}/block/{block_hash}")
        r.raise_for_status()
        block = r.json()
        prev_hash = block.get("previousblockhash")
        if not prev_hash:
            raise ValueError("could not resolve previous Bitcoin block")
        r = await client.get(f"{base}/block/{prev_hash}")
        r.raise_for_status()
        prev = r.json()

    snapshot_ts = int(snapshot_time.timestamp())
    if int(block["timestamp"]) < snapshot_ts:
        raise ValueError("Bitcoin block is older than the frozen snapshot")
    if int(prev["timestamp"]) >= snapshot_ts:
        raise ValueError("this is not the first Bitcoin block after the frozen snapshot")
    return block


async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if denied(update, settings) or not update.message:
        return
    parts = [part.strip() for part in " ".join(context.args).split("|")]
    if len(parts) != 3 or not all(parts):
        await update.message.reply_text(
            "Usage: /draw campaign_slug | bitcoin_block_height | bitcoin_block_hash\n"
            "Run /snapshot first, then use the first Bitcoin block mined after the snapshot time."
        )
        return
    slug, height_raw, block_hash = parts
    if not height_raw.isdigit():
        await update.message.reply_text("Bitcoin block height must be an integer.")
        return
    campaign = db.get_campaign(slug)
    if not campaign:
        await update.message.reply_text("Campaign not found.")
        return
    if db.draw_for_campaign(campaign.id):
        await update.message.reply_text("This campaign has already been drawn.")
        return
    snapshot = db.draw_snapshot(campaign.id)
    if not snapshot:
        await update.message.reply_text("No frozen snapshot. Run /snapshot <slug> first.")
        return

    try:
        snapshot_time = parse_datetime(snapshot["created_at"])
        block = await _verify_first_bitcoin_block(int(height_raw), block_hash, snapshot_time)
    except Exception as exc:
        await update.message.reply_text(f"Bitcoin entropy verification failed: {exc}")
        return

    entrants = [tuple(map(int, item)) for item in json.loads(snapshot["entrants_json"])]
    draw_count = min(len(entrants), campaign.num_winners + 5)
    ordered = weighted_draw(entrants, block_hash.lower(), draw_count)
    winners = ordered[:campaign.num_winners]
    reserves = ordered[campaign.num_winners:]
    seed_source = f"bitcoin:first-block-after-snapshot:height={height_raw}:hash={block_hash.lower()}"
    digest = db.save_draw(
        campaign,
        block_hash.lower(),
        entrants,
        winners,
        snapshot["verification_summary"],
        reserves=reserves,
        seed_source=seed_source,
    )
    db.log_admin_action(campaign.id, admin_id(update), "draw", {
        "snapshot_digest": snapshot["entrant_digest"],
        "seed_source": seed_source,
        "winners": winners,
        "reserves": reserves,
    })
    lines = [
        f"<b>🎁 Draw complete — {escape(campaign.name)}</b>\n",
        f"Entrants: <b>{len(entrants)}</b>",
        f"Tickets: <b>{sum(t for _, t in entrants)}</b>",
        f"Bitcoin block: <code>{height_raw}</code>",
        f"Seed/hash: <code>{escape(block_hash.lower())}</code>",
        f"Entrant SHA-256: <code>{digest}</code>\n",
        "<b>Winners:</b>",
    ]
    for index, uid in enumerate(winners, 1):
        lines.append(f"{index}. <code>{uid}</code>")
    if reserves:
        lines.append("\n<b>Ordered reserves:</b>")
        for index, uid in enumerate(reserves, 1):
            lines.append(f"R{index}. <code>{uid}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
