"""Read-only launch tools for owned-audience seed acquisition."""

from .context import is_admin, services
from .growth import _bot_username, _pct, build_promo_link, source_performance
from .reporting import reply_report
from .share_activation import sharing_source_performance

OWNED_AUDIENCES = ("meditation", "kriptofarsi", "trstudy")


async def cmd_owned_sources(update, context) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign or len(context.args) > 1:
        await update.message.reply_text("Usage: /owned_sources [campaign_slug]")
        return
    username = await _bot_username(context)
    acquisition = source_performance(db, campaign)
    rows = {row["source"]: row for row in acquisition["rows"]}
    sharing = {row["source"]: row for row in sharing_source_performance(db, campaign)["rows"]}
    lines = [
        f"Owned audiences — {campaign.slug}",
        f"Tracked from: {acquisition['tracking_started_at'] or 'no tracked start yet'}",
        "Campaign-to-date, first-touch attribution; not a post-deploy or 24h cohort.",
        "",
    ]
    for audience in OWNED_AUDIENCES:
        source = f"{audience}_b"
        row = rows.get(source, {})
        share = sharing.get(source, {})
        lines.extend([
            source,
            build_promo_link(username, audience, "b"),
            f"Prepare a post for the LIVE campaign: /promo_post {audience} b",
            f"starts={row.get('starts', 0)} entered={row.get('entered', 0)} "
            f"new={row.get('new_starts', 0)} returning={row.get('returning_starts', 0)}",
            f"start→enter={_pct(row.get('start_to_entered_pct'))} | "
            f"new start→enter={_pct(row.get('new_start_to_entered_pct'))}",
            f"holders={share.get('link_holders', 0)} with_open={share.get('holders_with_open', 0)} "
            f"unique_openers={share.get('unique_openers', 0)} | "
            f"holder→open={_pct(share.get('holder_to_open_pct'))}",
            f"joins={row.get('joins', 0)} active={row.get('active', 0)} "
            f"qualified={row.get('qualified', 0)}",
            "",
        ])
    lines.extend([
        "Links open the live campaign. Post preparation does not publish to a channel.",
        "Launch one audience at a time; save a baseline and posting time. Use /sources for auto-entry diagnostics.",
        "Repeat visitors keep their first source; legacy referral trees stay legacy/untracked.",
        "Post views and native share completion are not measured. Zero traffic is not a failed conversion.",
    ])
    await reply_report(update.message, "\n".join(lines))
