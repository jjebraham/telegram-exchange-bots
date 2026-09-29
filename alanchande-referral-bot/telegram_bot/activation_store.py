"""One-time outreach ledgers and observational outcomes; scoring stays in ReferralDB."""

import json
from collections import Counter
from datetime import timedelta

from referral_core import parse_datetime, utcnow
from referral_core.models import iso_utc

SEGMENTS = ("next_ticket", "first_friend")
CONTACT_COOLDOWN = timedelta(hours=24)


def activity_snapshot(db, campaign, user_id, now=None):
    now = now or utcnow()
    with db.connect() as conn:
        opens = conn.execute(
            """SELECT source,created_at FROM funnel_events WHERE campaign_id=?
               AND user_id=? AND event_type='referral_open_received'""",
            (campaign.id, user_id),
        ).fetchall()
        refs = conn.execute(
            "SELECT joined_user_id,joined_at FROM referrals WHERE campaign_id=? AND referrer_id=?",
            (campaign.id, user_id),
        ).fetchall()
        pending = conn.execute(
            """SELECT joined_user_id,created_at FROM pending_referrals
               WHERE campaign_id=? AND referrer_id=?""", (campaign.id, user_id),
        ).fetchall()
    open_ids = set()
    for row in opens:
        if not row["source"].startswith("candidate:"):
            continue
        try:
            candidate = int(row["source"].split(":", 1)[1])
        except ValueError:
            continue
        if candidate != user_id and parse_datetime(row["created_at"]) <= now:
            open_ids.add(candidate)
    joined = {int(r["joined_user_id"]) for r in refs if parse_datetime(r["joined_at"]) <= now}
    pending_ids = {int(r["joined_user_id"]) for r in pending if parse_datetime(r["created_at"]) <= now}
    return {
        "known_candidates": sorted(open_ids | joined | pending_ids),
        "confirmed_points": db.campaign_counts(campaign, user_id, now)["confirmed_points"],
    }


def eligibility(db, campaign, user_id, segment, now=None):
    """Return current counts and payload, or a reason to skip this recipient."""
    now = now or utcnow()
    if segment not in SEGMENTS:
        raise ValueError("Unknown activation segment")
    if not campaign.is_live(now):
        return None, "campaign_not_live"
    if now >= campaign.final_qualification_cutoff:
        return None, "invitation_deadline"
    payload = db.get_invite_link(campaign.id, user_id)
    prefix = f"ref_{campaign.id}_"
    if not payload or not payload.startswith(prefix) or len(payload) <= len(prefix):
        return None, "no_personal_deep_link"
    counts = db.campaign_counts(campaign, user_id, now)
    if campaign.max_points and counts["confirmed_points"] >= campaign.max_points:
        return None, "ticket_cap"
    with db.connect() as conn:
        recent = conn.execute(
            """SELECT 1 FROM funnel_events WHERE campaign_id=? AND user_id=?
               AND created_at>? AND created_at<=?
               AND (event_type LIKE 'nudge_%_sent' OR event_type='first_ticket_nudge_sent')
               LIMIT 1""", (campaign.id, user_id, iso_utc(now - CONTACT_COOLDOWN), iso_utc(now)),
        ).fetchone()
        recent_activation = conn.execute(
            """SELECT 1 FROM activation_recipients WHERE campaign_id=? AND user_id=?
               AND state='sent' AND sent_at>? AND sent_at<=? LIMIT 1""",
            (campaign.id, user_id, iso_utc(now - CONTACT_COOLDOWN), iso_utc(now)),
        ).fetchone()
        if segment == "first_friend":
            first = conn.execute(
                """SELECT source FROM funnel_events WHERE campaign_id=? AND user_id=?
                   AND event_type='bot_start' ORDER BY created_at,source LIMIT 1""",
                (campaign.id, user_id),
            ).fetchone()
            link = conn.execute(
                "SELECT created_at FROM invite_links WHERE campaign_id=? AND user_id=?",
                (campaign.id, user_id),
            ).fetchone()
    if recent or recent_activation:
        return None, "recent_contact"
    if segment == "next_ticket":
        if counts["confirmed_points"] != 1:
            return None, "not_one_confirmed_ticket"
    else:
        if not first or str(first["source"]).strip().lower() != "referral":
            return None, "not_referral_first_touch"
        if parse_datetime(link["created_at"]) > now - CONTACT_COOLDOWN:
            return None, "new_link_holder"
        if activity_snapshot(db, campaign, user_id, now)["known_candidates"]:
            return None, "already_has_downstream_activity"
    return {"user_id": user_id, "counts": counts, "payload": payload}, None


def eligible_recipients(db, campaign, segment, now=None):
    now = now or utcnow()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM invite_links WHERE campaign_id=? ORDER BY user_id", (campaign.id,),
        ).fetchall()
    result = []
    for row in rows:
        recipient, _ = eligibility(db, campaign, int(row["user_id"]), segment, now)
        if recipient:
            result.append(recipient)
    return result


def get_run(db, campaign_id, segment):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM activation_runs WHERE campaign_id=? AND segment=?", (campaign_id, segment),
        ).fetchone()
    return dict(row) if row else None


def start_run(db, campaign, segment, admin_id, user_ids, now=None):
    """Freeze the preview audience once; later confirmations cannot add recipients."""
    if segment not in SEGMENTS:
        raise ValueError("Unknown activation segment")
    with db.connect() as conn:
        created = conn.execute(
            """INSERT INTO activation_runs(campaign_id,segment,admin_id,started_at)
               VALUES(?,?,?,?) ON CONFLICT(campaign_id,segment) DO NOTHING""",
            (campaign.id, segment, admin_id, iso_utc(now or utcnow())),
        ).rowcount == 1
        if created:
            conn.executemany(
                "INSERT INTO activation_recipients(campaign_id,segment,user_id) VALUES(?,?,?)",
                [(campaign.id, segment, uid) for uid in sorted(set(user_ids))],
            )
    return created


def pending_recipients(db, campaign_id, segment):
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT user_id FROM activation_recipients
               WHERE campaign_id=? AND segment=? AND state='pending' ORDER BY user_id""",
            (campaign_id, segment),
        ).fetchall()
    return [int(r["user_id"]) for r in rows]


def claim_recipient(db, campaign, segment, user_id, baseline, now=None):
    """An atomic claim precedes Telegram I/O, including on resumed runs."""
    with db.connect() as conn:
        return conn.execute(
            """UPDATE activation_recipients SET state='sending',attempted_at=?,baseline_json=?
               WHERE campaign_id=? AND segment=? AND user_id=? AND state='pending'""",
            (iso_utc(now or utcnow()), json.dumps(baseline, sort_keys=True), campaign.id, segment, user_id),
        ).rowcount == 1


def finish_recipient(db, campaign_id, segment, user_id, state, *, message_id=None, reason=None, now=None):
    if state not in {"sent", "failed", "skipped", "unknown"}:
        raise ValueError("Invalid terminal delivery state")
    with db.connect() as conn:
        conn.execute(
            """UPDATE activation_recipients SET state=?,sent_at=?,message_id=?,reason=?
               WHERE campaign_id=? AND segment=? AND user_id=? AND state IN ('pending','sending')""",
            (state, iso_utc(now or utcnow()) if state == "sent" else None,
             message_id, reason, campaign_id, segment, user_id),
        )


def refresh_attempt(db, campaign, segment, user_id, baseline, now):
    with db.connect() as conn:
        conn.execute(
            """UPDATE activation_recipients SET attempted_at=?,baseline_json=?
               WHERE campaign_id=? AND segment=? AND user_id=? AND state='sending'""",
            (iso_utc(now), json.dumps(baseline, sort_keys=True), campaign.id, segment, user_id),
        )


def finish_run(db, campaign_id, segment, now=None):
    with db.connect() as conn:
        conn.execute(
            """UPDATE activation_runs SET finished_at=COALESCE(finished_at,?) WHERE campaign_id=? AND segment=?
               AND NOT EXISTS (SELECT 1 FROM activation_recipients r WHERE
                   r.campaign_id=activation_runs.campaign_id AND r.segment=activation_runs.segment
                   AND r.state='pending')""", (iso_utc(now or utcnow()), campaign_id, segment),
        )


def activation_report(db, campaign, segment, now=None):
    now = now or utcnow()
    run = get_run(db, campaign.id, segment)
    if not run:
        return None
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM activation_recipients WHERE campaign_id=? AND segment=?",
            (campaign.id, segment),
        ).fetchall()
        opens = conn.execute(
            """SELECT user_id,source,created_at FROM funnel_events WHERE campaign_id=?
               AND event_type='referral_open_received'""", (campaign.id,),
        ).fetchall()
        refs = conn.execute(
            "SELECT referrer_id,joined_user_id,joined_at FROM referrals WHERE campaign_id=?", (campaign.id,),
        ).fetchall()
    states = Counter(r["state"] for r in rows)
    with_open, with_join, advanced = set(), set(), set()
    fresh_opens, fresh_joins = set(), set()
    for row in rows:
        if row["state"] != "sent" or parse_datetime(row["sent_at"]) > now:
            continue
        uid = int(row["user_id"])
        # Begin at confirmed delivery, never at the run's global start time.
        since = parse_datetime(row["sent_at"])
        baseline = json.loads(row["baseline_json"])
        known = set(baseline["known_candidates"])
        for event in opens:
            if event["user_id"] != uid or not event["source"].startswith("candidate:"):
                continue
            try:
                candidate = int(event["source"].split(":", 1)[1])
            except ValueError:
                continue
            if candidate == uid or candidate in known:
                continue
            if since <= parse_datetime(event["created_at"]) <= now:
                with_open.add(uid)
                fresh_opens.add((uid, candidate))
        for ref in refs:
            candidate = int(ref["joined_user_id"])
            if ref["referrer_id"] != uid or candidate in known or candidate == uid:
                continue
            if since <= parse_datetime(ref["joined_at"]) <= now:
                with_join.add(uid)
                fresh_joins.add((uid, candidate))
        if db.campaign_counts(campaign, uid, now)["confirmed_points"] > baseline["confirmed_points"]:
            advanced.add(uid)
    return {
        "run": run, "eligible": len(rows), "states": dict(states),
        "with_new_open": len(with_open), "new_opens": len(fresh_opens),
        "with_new_join": len(with_join), "new_joins": len(fresh_joins),
        "with_more_tickets_now": len(advanced),
    }
