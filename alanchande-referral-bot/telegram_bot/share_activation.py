from __future__ import annotations

from collections import defaultdict
from statistics import median

from telegram import Update
from telegram.ext import ContextTypes

from referral_core import parse_datetime
from . import reminders
from .context import is_admin, services
from .growth import cmd_sources as base_cmd_sources
from .reporting import reply_report


def record_referral_open_received(
    db,
    campaign_id: int,
    referrer_id: int,
    candidate_id: int,
) -> bool:
    """Attribute the candidate's first observable open to the link owner.

    Returns True only for the first unique referrer/candidate open. That lets
    the caller send one useful "someone opened your link" notification without
    spamming the referrer when the same candidate re-opens the deep link.
    """
    referrer_id = int(referrer_id)
    candidate_id = int(candidate_id)
    if referrer_id == candidate_id:
        return False

    source = f"candidate:{candidate_id}"
    # ReferralDB exposes connect(); the small fallback keeps lightweight test
    # doubles compatible while production gets exact de-duplication.
    if hasattr(db, "connect"):
        with db.connect() as conn:
            existing = conn.execute(
                """SELECT 1 FROM funnel_events
                   WHERE campaign_id=? AND user_id=?
                     AND event_type='referral_open_received' AND source=?
                   LIMIT 1""",
                (campaign_id, referrer_id, source),
            ).fetchone()
        if existing:
            return False

    db.track_funnel_event(
        campaign_id,
        referrer_id,
        "referral_open_received",
        source,
    )
    return True


def zero_open_nudge_candidates(db, campaign_id: int, cutoff, limit: int = 100) -> list[dict]:
    """Participants whose personal link has produced no observable open yet.

    New traffic uses referral_open_received for exact attribution. Pending and
    joined referrals are retained as a historical fallback so participants who
    already produced downstream activity before this instrumentation do not get
    an incorrect zero-open nudge.
    """
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT l.user_id,l.invite_link,l.created_at
               FROM invite_links l
               WHERE l.campaign_id=? AND l.created_at<=?
                 AND EXISTS (
                     SELECT 1 FROM funnel_events e
                     WHERE e.campaign_id=l.campaign_id AND e.user_id=l.user_id
                       AND e.event_type='entered_contest'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM funnel_events e
                     WHERE e.campaign_id=l.campaign_id AND e.user_id=l.user_id
                       AND e.event_type='referral_open_received'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM pending_referrals p
                     WHERE p.campaign_id=l.campaign_id AND p.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM referrals r
                     WHERE r.campaign_id=l.campaign_id AND r.referrer_id=l.user_id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM funnel_events e
                     WHERE e.campaign_id=l.campaign_id AND e.user_id=l.user_id
                       AND e.event_type='nudge_early_share_sent'
                 )
               ORDER BY l.created_at ASC
               LIMIT ?""",
            (campaign_id, cutoff.isoformat(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def install_zero_open_nudge_filter() -> None:
    """Make the existing 2-hour nudge worker use exact zero-open semantics."""
    reminders._early_share_nudge_candidates = zero_open_nudge_candidates


def _canonical_source(raw: str) -> str:
    """Collapse accidental historical A/B suffix duplication."""
    source = str(raw or "organic").strip().lower()
    parts = source.rsplit("_", 2)
    if (
        len(parts) == 3
        and parts[-2] in {"a", "b"}
        and parts[-1] in {"a", "b"}
    ):
        return f"{parts[0]}_{parts[-1]}"
    return source


def _first_touch_sources(db, campaign_id: int):
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT user_id,source,created_at FROM funnel_events
               WHERE campaign_id=? AND event_type='bot_start'
               ORDER BY created_at ASC,user_id ASC,source ASC""",
            (campaign_id,),
        ).fetchall()

    first: dict[int, str] = {}
    tracking_started = None

    for row in rows:
        if tracking_started is None:
            tracking_started = parse_datetime(row["created_at"])

        first.setdefault(
            int(row["user_id"]),
            _canonical_source(row["source"] or "organic"),
        )

    return first, tracking_started


def sharing_source_performance(db, campaign) -> dict:
    """Unique link-holder sharing outcomes by the referrer's first-touch source."""
    first_source, tracking_started = _first_touch_sources(db, campaign.id)
    with db.connect() as conn:
        links = conn.execute(
            """SELECT user_id,created_at FROM invite_links
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()
        received = conn.execute(
            """SELECT user_id,source,created_at FROM funnel_events
               WHERE campaign_id=? AND event_type='referral_open_received'""",
            (campaign.id,),
        ).fetchall()
        candidate_opens = conn.execute(
            """SELECT user_id,created_at FROM funnel_events
               WHERE campaign_id=? AND event_type='referral_open'""",
            (campaign.id,),
        ).fetchall()
        pending = conn.execute(
            """SELECT joined_user_id,referrer_id FROM pending_referrals
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()
        refs = conn.execute(
            """SELECT joined_user_id,referrer_id FROM referrals
               WHERE campaign_id=?""",
            (campaign.id,),
        ).fetchall()

    link_created = {
        int(row["user_id"]): parse_datetime(row["created_at"])
        for row in links
    }

    def holder_source(user_id: int) -> str:
        created_at = link_created.get(user_id)

        if (
            tracking_started is not None
            and created_at is not None
            and created_at < tracking_started
        ):
            return "legacy/untracked"

        return first_source.get(user_id, "legacy/untracked")

    candidate_to_referrer: dict[int, int] = {}
    for row in list(pending) + list(refs):
        candidate_to_referrer.setdefault(int(row["joined_user_id"]), int(row["referrer_id"]))

    open_records: set[tuple[int, int]] = set()
    first_open_at: dict[int, object] = {}

    for row in received:
        referrer_id = int(row["user_id"])
        source = str(row["source"] or "")
        if not source.startswith("candidate:"):
            continue
        try:
            candidate_id = int(source.split(":", 1)[1])
        except (TypeError, ValueError):
            continue
        if candidate_id == referrer_id:
            continue
        open_records.add((referrer_id, candidate_id))
        opened_at = parse_datetime(row["created_at"])
        old = first_open_at.get(referrer_id)
        if old is None or opened_at < old:
            first_open_at[referrer_id] = opened_at

    # Historical fallback for opens recorded before referral_open_received existed.
    candidate_open_time: dict[int, object] = {}
    for row in candidate_opens:
        candidate_id = int(row["user_id"])
        opened_at = parse_datetime(row["created_at"])
        old = candidate_open_time.get(candidate_id)
        if old is None or opened_at < old:
            candidate_open_time[candidate_id] = opened_at
    for candidate_id, opened_at in candidate_open_time.items():
        referrer_id = candidate_to_referrer.get(candidate_id)
        if referrer_id is None or referrer_id == candidate_id:
            continue
        open_records.add((referrer_id, candidate_id))
        old = first_open_at.get(referrer_id)
        if old is None or opened_at < old:
            first_open_at[referrer_id] = opened_at

    pending_referrers = {int(row["referrer_id"]) for row in pending}
    joined_referrers = {int(row["referrer_id"]) for row in refs}
    referrers_with_open = {referrer_id for referrer_id, _ in open_records}

    buckets: dict[str, dict] = defaultdict(lambda: {
        "link_holders": set(),
        "holders_with_open": set(),
        "holders_with_candidate": set(),
        "holders_with_join": set(),
        "unique_openers": set(),
        "first_open_minutes": [],
    })

    for referrer_id in link_created:
        source = holder_source(referrer_id)
        bucket = buckets[source]
        bucket["link_holders"].add(referrer_id)
        if referrer_id in referrers_with_open:
            bucket["holders_with_open"].add(referrer_id)
        if referrer_id in pending_referrers or referrer_id in joined_referrers:
            bucket["holders_with_candidate"].add(referrer_id)
        if referrer_id in joined_referrers:
            bucket["holders_with_join"].add(referrer_id)
        opened_at = first_open_at.get(referrer_id)
        if opened_at is not None:
            delta = (opened_at - link_created[referrer_id]).total_seconds() / 60.0
            if delta >= 0:
                bucket["first_open_minutes"].append(delta)

    for referrer_id, candidate_id in open_records:
        source = holder_source(referrer_id)
        buckets[source]["unique_openers"].add(candidate_id)

    rows = []
    for source, bucket in buckets.items():
        holders = len(bucket["link_holders"])
        with_open = len(bucket["holders_with_open"])
        rows.append({
            "source": source,
            "link_holders": holders,
            "holders_with_open": with_open,
            "holders_with_candidate": len(bucket["holders_with_candidate"]),
            "holders_with_join": len(bucket["holders_with_join"]),
            "unique_openers": len(bucket["unique_openers"]),
            "holder_to_open_pct": round(with_open * 100.0 / holders, 1) if holders else None,
            "median_first_open_minutes": (
                round(float(median(bucket["first_open_minutes"])), 1)
                if bucket["first_open_minutes"] else None
            ),
        })

    rows.sort(key=lambda row: (
        row["source"] == "legacy/untracked",
        -row["link_holders"],
        -row["holders_with_open"],
        row["source"],
    ))
    return {"rows": rows}


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _minutes(value) -> str:
    if value is None:
        return "n/a"
    if value < 60:
        return f"{value:g}m"
    hours = value / 60.0
    return f"{hours:.1f}h"


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Preserve /sources and append unique link-holder sharing activation metrics."""
    await base_cmd_sources(update, context)

    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    if not campaign:
        return

    report = sharing_source_performance(db, campaign)
    lines = [
        f"🔁 Sharing activation — {campaign.slug}",
        "Unique link holders; repeated opens by the same candidate are de-duplicated.",
        "",
    ]
    if not report["rows"]:
        lines.append("No sharing data yet.")
    for row in report["rows"]:
        lines.extend([
            f"• {row['source']}",
            f"  holders={row['link_holders']} with_open={row['holders_with_open']} "
            f"with_candidate={row['holders_with_candidate']} with_join={row['holders_with_join']}",
            f"  unique_openers={row['unique_openers']} | holder→open={_pct(row['holder_to_open_pct'])} "
            f"| median link→first open={_minutes(row['median_first_open_minutes'])}",
        ])
    lines.extend([
        "",
        "Exact open attribution is recorded from this deployment forward; older opens are inferred when a pending/joined candidate can be matched.",
        "Telegram's native share-sheet completion is still not visible to the bot; downstream link opens are the reliable outcome metric.",
    ])
    await reply_report(update.message, "\n".join(lines))
