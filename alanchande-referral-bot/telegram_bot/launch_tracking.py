"""Immutable acquisition markers and observational cohorts; no referral mutations."""

import json
import re
from datetime import timedelta

from referral_core import parse_datetime, utcnow
from .context import is_admin, services
from .growth import canonical_promo_source, source_performance, _pct
from .reporting import reply_report

_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")


def mark_launch(db, campaign, source, label, admin_id, now=None):
    if not _SLUG.fullmatch(source) or not _SLUG.fullmatch(label):
        raise ValueError("Use lowercase letters, digits, underscores or hyphens (max 48 characters).")
    source = canonical_promo_source(source)
    now = now or utcnow()
    baseline = next((row for row in source_performance(db, campaign)["rows"]
                     if row["source"] == source), {})
    with db.connect() as conn:
        result = conn.execute(
            """INSERT INTO growth_launches VALUES(?,?,?,?,?,?)
               ON CONFLICT(campaign_id,label) DO NOTHING""",
            (campaign.id, label, source, now.isoformat(), admin_id, json.dumps(baseline)),
        )
        created = result.rowcount == 1
        row = conn.execute(
            "SELECT * FROM growth_launches WHERE campaign_id=? AND label=?",
            (campaign.id, label),
        ).fetchone()
    return dict(row), created


def launch_report(db, campaign_id, label, now=None):
    now = now or utcnow()
    with db.connect() as conn:
        marker = conn.execute(
            "SELECT * FROM growth_launches WHERE campaign_id=? AND label=?",
            (campaign_id, label),
        ).fetchone()
        if marker is None:
            return None
        events = conn.execute(
            """SELECT user_id,event_type,source,created_at FROM funnel_events
               WHERE campaign_id=? AND event_type IN
               ('bot_start','entered_contest','referral_open_received')
               ORDER BY created_at,source""", (campaign_id,),
        ).fetchall()
        links = conn.execute(
            "SELECT user_id,created_at FROM invite_links WHERE campaign_id=?",
            (campaign_id,),
        ).fetchall()
    start = parse_datetime(marker["started_at"])
    link_times = {r["user_id"]: parse_datetime(r["created_at"]) for r in links}
    first = {}
    entered = set()
    opens = {}
    for event in events:
        when = parse_datetime(event["created_at"])
        if when > now:
            continue
        uid = event["user_id"]
        if event["event_type"] == "bot_start":
            first.setdefault(uid, (when, canonical_promo_source(event["source"] or "organic")))
        elif event["event_type"] == "entered_contest" and when >= start:
            entered.add(uid)
        elif event["event_type"] == "referral_open_received":
            match = re.fullmatch(r"candidate:(\d+)", event["source"] or "")
            if match and int(match[1]) != uid:
                opens.setdefault(uid, []).append((when, int(match[1])))
    cohort = {uid for uid, (when, source) in first.items()
              if start <= when <= now and source == marker["source"]
              and (uid not in link_times or link_times[uid] >= when)}
    holders = {uid for uid in cohort if uid in link_times and link_times[uid] <= now}
    mature = {uid for uid in holders if link_times[uid] + timedelta(hours=24) <= now}
    activated = set()
    with_open = set()
    openers = set()
    for uid in holders:
        for when, candidate in opens.get(uid, []):
            if link_times[uid] <= when <= now:
                with_open.add(uid)
                openers.add(candidate)
                if when <= link_times[uid] + timedelta(hours=24):
                    activated.add(uid)
    return {
        "marker": dict(marker), "as_of": now.isoformat(),
        "starts": len(cohort), "entered": len(cohort & entered),
        "holders": len(holders), "with_open": len(with_open), "unique_openers": len(openers),
        "mature": len(mature), "activated_24h": len(mature & activated),
        "pending": len(holders - mature), "pending_with_open": len(activated - mature),
    }


async def cmd_launch_mark(update, context):
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.live_campaign()
    if len(context.args) != 2 or not campaign:
        await update.message.reply_text("Usage: /launch_mark <source> <label> (requires a live campaign)")
        return
    try:
        marker, created = mark_launch(db, campaign, *context.args, update.effective_user.id)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    baseline = json.loads(marker["baseline_json"])
    await reply_report(update.message,
        f"{'Launch marker saved' if created else 'Label already exists; original marker preserved'} — {campaign.slug}\n"
        f"{marker['label']} | {marker['source']} | {marker['started_at']}\n"
        f"Baseline: starts={baseline.get('starts', 0)} entered={baseline.get('entered', 0)} "
        f"links={baseline.get('links', 0)}\n"
        f"/launch_report {marker['label']} {campaign.slug}\n"
        "This records the measurement start now; it does not publish or prove a post was published.")


async def cmd_launch_report(update, context):
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    if not 1 <= len(context.args) <= 2:
        await update.message.reply_text("Usage: /launch_report <label> [campaign_slug]")
        return
    campaign = db.get_campaign(context.args[1]) if len(context.args) == 2 else db.live_campaign()
    report = launch_report(db, campaign.id, context.args[0]) if campaign else None
    if report is None:
        await update.message.reply_text("Launch marker not found. Check the label and campaign.")
        return
    r = report
    marker = r["marker"]
    baseline = json.loads(marker["baseline_json"])
    entry_rate = r['entered'] * 100 / r['starts'] if r['starts'] else None
    activation_rate = r['activated_24h'] * 100 / r['mature'] if r['mature'] else None
    await reply_report(update.message, "\n".join([
        f"Launch — {campaign.slug} / {marker['label']} / {marker['source']}",
        f"Since: {marker['started_at']} | As of: {r['as_of']}",
        f"Saved baseline: starts={baseline.get('starts', 0)} entered={baseline.get('entered', 0)} links={baseline.get('links', 0)}",
        "New first-touch users since marker (existing link holders excluded):",
        f"starts={r['starts']} entered={r['entered']} | start→enter={_pct(entry_rate)}",
        f"holders={r['holders']} with_open={r['with_open']} unique_openers={r['unique_openers']}",
        f"24h completed: holders={r['mature']} opened_within_24h={r['activated_24h']} | activation={_pct(activation_rate)}",
        f"24h pending: holders={r['pending']} already_with_open={r['pending_with_open']} (excluded from completed rate)",
        "24h starts at personal-link creation. Only exact recorded downstream opens count; repeats and self-opens are excluded.",
        "Cohort counts are not subtraction from the baseline. Earlier first-touch users stay excluded even if they enter later.",
        "This is an ongoing cohort, not a fixed 24h acquisition window. Overlapping markers may include the same users; do not add them together.",
        "Post views, native Share completion and causal attribution to a specific post are not measured.",
    ]))
