from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Sequence

from .models import Campaign, entrant_snapshot, iso_utc, parse_datetime, points_from_invites, utcnow


class ReportsMixin:
    def leaderboard(self, campaign: Campaign, limit: int = 10,
                    now: datetime | None = None) -> list[dict]:
        """Return a live leaderboard ranked by provisional/current score."""
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT r.referrer_id,
                          SUM(CASE WHEN r.active=1 THEN 1 ELSE 0 END) AS active_count,
                          SUM(CASE WHEN r.active=1 AND r.stay_since<=? THEN 1 ELSE 0 END) AS qualified,
                          u.first_name,u.username
                   FROM referrals r JOIN users u ON u.user_id=r.referrer_id
                   WHERE r.campaign_id=?
                   GROUP BY r.referrer_id
                   HAVING SUM(CASE WHEN r.active=1 THEN 1 ELSE 0 END)>0""",
                (cutoff, campaign.id),
            ).fetchall()

        result = []
        for row in rows:
            active = int(row["active_count"] or 0)
            qualified = int(row["qualified"] or 0)
            current_points = points_from_invites(
                active, campaign.invites_per_point, campaign.max_points
            )
            if current_points <= 0:
                continue
            confirmed_points = points_from_invites(
                qualified, campaign.invites_per_point, campaign.max_points
            )
            result.append({
                "user_id": int(row["referrer_id"]),
                "active": active,
                "qualified": qualified,
                "current_points": current_points,
                "confirmed_points": confirmed_points,
                "points": confirmed_points,
                "first_name": row["first_name"],
                "username": row["username"],
            })

        result.sort(
            key=lambda row: (
                -row["current_points"],
                -row["active"],
                -row["confirmed_points"],
                row["user_id"],
            )
        )
        return result[:max(1, limit)]

    def leaderboard_position(self, campaign: Campaign, user_id: int,
                             now: datetime | None = None) -> tuple[int | None, int]:
        rows = self.leaderboard(campaign, limit=100000, now=now)
        for index, row in enumerate(rows, 1):
            if int(row["user_id"]) == int(user_id):
                return index, len(rows)
        return None, len(rows)

    def closest_pending_seconds(self, campaign: Campaign, referrer_id: int,
                                now: datetime | None = None) -> int | None:
        now_dt = (now or utcnow()).astimezone(campaign.start_dt.tzinfo)
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            row = conn.execute(
                """SELECT MIN(stay_since) AS oldest FROM referrals
                   WHERE campaign_id=? AND referrer_id=? AND active=1 AND stay_since>?""",
                (campaign.id, referrer_id, cutoff),
            ).fetchone()
        if not row or not row["oldest"]:
            return None
        qualifies_at = parse_datetime(row["oldest"]) + timedelta(hours=campaign.min_stay_hours)
        return max(0, int((qualifies_at - utcnow() if now is None else qualifies_at - now.astimezone(qualifies_at.tzinfo)).total_seconds()))

    def confirmed_entrants(self, campaign: Campaign, at: datetime | None = None,
                           eligible_user_ids: set[int] | None = None) -> list[tuple[int, int]]:
        """Confirmed final-draw entrants at a specific reference instant."""
        cutoff = iso_utc(campaign.cutoff(at))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT referrer_id,COUNT(*) AS qualified FROM referrals
                   WHERE campaign_id=? AND active=1 AND stay_since<=? GROUP BY referrer_id""",
                (campaign.id, cutoff),
            ).fetchall()
        result = []
        for row in rows:
            uid = int(row["referrer_id"])
            if eligible_user_ids is not None and uid not in eligible_user_ids:
                continue
            points = points_from_invites(row["qualified"], campaign.invites_per_point, campaign.max_points)
            if points > 0:
                result.append((uid, points))
        return sorted(result)

    def current_entrants(self, campaign: Campaign, now: datetime | None = None,
                         eligible_user_ids: set[int] | None = None) -> list[tuple[int, int]]:
        """Backward-compatible alias. Final draw code should use confirmed_entrants()."""
        return self.confirmed_entrants(campaign, at=now, eligible_user_ids=eligible_user_ids)

    def entrant_user_ids(self, campaign: Campaign, now: datetime | None = None) -> list[int]:
        return [uid for uid, _ in self.confirmed_entrants(campaign, at=now)]

    def participant_count(self, campaign_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM invite_links WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return int(row["n"])

    def track_funnel_event(self, campaign_id: int, user_id: int, event_type: str,
                           source: str = "", now: datetime | None = None) -> None:
        """Record one unique funnel event per user/campaign/type/source."""
        event = event_type.strip().lower()[:64]
        src = source.strip().lower()[:64]
        if not event:
            return
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO funnel_events(campaign_id,user_id,event_type,source,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(campaign_id,user_id,event_type,source) DO NOTHING""",
                (campaign_id, user_id, event, src, ts),
            )

    def funnel_stats(self, campaign: Campaign, now: datetime | None = None) -> dict:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            event_rows = conn.execute(
                """SELECT event_type,COUNT(DISTINCT user_id) AS n
                   FROM funnel_events WHERE campaign_id=? GROUP BY event_type""",
                (campaign.id,),
            ).fetchall()
            source_rows = conn.execute(
                """SELECT source,COUNT(DISTINCT user_id) AS n
                   FROM funnel_events
                   WHERE campaign_id=? AND event_type='bot_start'
                   GROUP BY source ORDER BY n DESC,source ASC""",
                (campaign.id,),
            ).fetchall()
            candidate_row = conn.execute(
                """SELECT COUNT(*) AS n FROM (
                       SELECT joined_user_id FROM pending_referrals WHERE campaign_id=?
                       UNION
                       SELECT joined_user_id FROM referrals WHERE campaign_id=?
                   )""",
                (campaign.id, campaign.id),
            ).fetchone()
            referral_row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,
                          SUM(CASE WHEN active=1 AND stay_since<=? THEN 1 ELSE 0 END) AS qualified
                   FROM referrals WHERE campaign_id=?""",
                (cutoff, campaign.id),
            ).fetchone()

        events = {row["event_type"]: int(row["n"] or 0) for row in event_rows}
        return {
            "bot_starts": events.get("bot_start", 0),
            "entered_contest": events.get("entered_contest", 0),
            "referral_opens": events.get("referral_open", 0),
            "participants_with_links": self.participant_count(campaign.id),
            "referral_candidates": int(candidate_row["n"] or 0),
            "joined_referrals": int(referral_row["total"] or 0),
            "active_referrals": int(referral_row["active"] or 0),
            "qualified_referrals": int(referral_row["qualified"] or 0),
            "sources": [
                {"source": row["source"] or "organic", "count": int(row["n"] or 0)}
                for row in source_rows
            ],
        }

    def admin_stats(self, campaign: Campaign, now: datetime | None = None) -> dict[str, int]:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                   SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,
                   SUM(CASE WHEN active=1 AND stay_since<=? THEN 1 ELSE 0 END) AS qualified,
                   SUM(CASE WHEN active=1 AND stay_since>? THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS left_count
                   FROM referrals WHERE campaign_id=?""",
                (cutoff, cutoff, campaign.id),
            ).fetchone()
        entrants = self.confirmed_entrants(campaign, at=now)
        return {
            "participants": self.participant_count(campaign.id),
            "referrals_total": int(row["total"] or 0), "active": int(row["active"] or 0),
            "qualified": int(row["qualified"] or 0), "pending": int(row["pending"] or 0),
            "left": int(row["left_count"] or 0), "entrants": len(entrants),
            "tickets": sum(tickets for _, tickets in entrants),
        }

    def audit_user(self, campaign: Campaign, user_id: int,
                   now: datetime | None = None) -> dict:
        counts = self.campaign_counts(campaign, user_id, now)
        with self.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            link = conn.execute(
                "SELECT invite_link FROM invite_links WHERE campaign_id=? AND user_id=?",
                (campaign.id, user_id),
            ).fetchone()
            referred_by = conn.execute(
                """SELECT referrer_id,active,stay_since,left_at FROM referrals
                   WHERE campaign_id=? AND joined_user_id=?""",
                (campaign.id, user_id),
            ).fetchone()
        return {
            "user": dict(user) if user else None,
            "invite_link": link["invite_link"] if link else None,
            "counts": counts,
            "referred_by": dict(referred_by) if referred_by else None,
        }

    def unnotified_qualified(self, campaign: Campaign, limit: int = 100,
                             now: datetime | None = None) -> list[dict]:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,referrer_id,joined_user_id,joined_first_name,joined_username
                   FROM referrals WHERE campaign_id=? AND active=1 AND stay_since<=?
                   AND qualified_notified_at IS NULL ORDER BY id LIMIT ?""",
                (campaign.id, cutoff, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_qualification_notified(self, referral_id: int,
                                    now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            row = conn.execute(
                "SELECT campaign_id,joined_user_id,referrer_id FROM referrals WHERE id=?",
                (referral_id,),
            ).fetchone()
            conn.execute(
                "UPDATE referrals SET qualified_notified_at=?,updated_at=? WHERE id=?",
                (ts, ts, referral_id),
            )
            if row:
                self._event(
                    conn, int(row["campaign_id"]), int(row["joined_user_id"]),
                    int(row["referrer_id"]), "qualified", ts,
                )

    def save_draw_snapshot(self, campaign: Campaign, entrants: Sequence[tuple[int, int]],
                           verification_summary: str, now: datetime | None = None) -> str:
        payload, digest = entrant_snapshot(entrants)
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT entrant_digest FROM draw_snapshots WHERE campaign_id=?", (campaign.id,)
            ).fetchone()
            if existing:
                if existing["entrant_digest"] != digest:
                    raise ValueError("campaign already has a different frozen entrant snapshot")
                return str(existing["entrant_digest"])
            conn.execute(
                """INSERT INTO draw_snapshots(
                       campaign_id,entrants_json,entrant_digest,verification_summary,created_at
                   ) VALUES(?,?,?,?,?)""",
                (campaign.id, payload, digest, verification_summary, ts),
            )
        return digest

    def draw_snapshot(self, campaign_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM draw_snapshots WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return dict(row) if row else None

    def save_draw(self, campaign: Campaign, seed: str, entrants: Sequence[tuple[int, int]],
                  winners: Sequence[int], verification_summary: str,
                  now: datetime | None = None, *, reserves: Sequence[int] = (),
                  seed_source: str = "") -> str:
        payload, digest = entrant_snapshot(entrants)
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM draws WHERE campaign_id=?", (campaign.id,)).fetchone():
                raise ValueError("campaign already has a recorded draw")
            conn.execute(
                """INSERT INTO draws(campaign_id,seed,seed_source,entrants_json,winners_json,
                   reserves_json,entrant_digest,verification_summary,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    campaign.id, seed, seed_source, payload,
                    json.dumps(list(winners), separators=(",", ":")),
                    json.dumps(list(reserves), separators=(",", ":")),
                    digest, verification_summary, ts,
                ),
            )
            conn.execute(
                "UPDATE campaigns SET status='drawn',updated_at=? WHERE id=?", (ts, campaign.id)
            )
        return digest

    def draw_for_campaign(self, campaign_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM draws WHERE campaign_id=?", (campaign_id,)).fetchone()
        return dict(row) if row else None

    def admin_actions(self, campaign_id: int | None = None, limit: int = 30) -> list[dict]:
        with self.connect() as conn:
            if campaign_id is None:
                rows = conn.execute(
                    "SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT ?", (max(1, limit),)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM admin_audit_log WHERE campaign_id=?
                       ORDER BY id DESC LIMIT ?""",
                    (campaign_id, max(1, limit)),
                ).fetchall()
        return [dict(row) for row in rows]

    def fraud_flags(self, campaign: Campaign) -> list[dict]:
        """Flag-only heuristics. Never auto-disqualify based on this report."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT referrer_id,joined_at,left_at,active FROM referrals
                   WHERE campaign_id=? ORDER BY referrer_id,joined_at""",
                (campaign.id,),
            ).fetchall()
        groups: dict[int, list] = {}
        for row in rows:
            groups.setdefault(int(row["referrer_id"]), []).append(row)

        flagged = []
        for referrer_id, refs in groups.items():
            times = [parse_datetime(row["joined_at"]) for row in refs]
            max_hour = 0
            left = sum(1 for row in refs if not row["active"])
            for i, start in enumerate(times):
                j = i
                while j < len(times) and times[j] - start <= timedelta(hours=1):
                    j += 1
                max_hour = max(max_hour, j - i)
            reasons = []
            if max_hour >= 6:
                reasons.append(f"velocity:{max_hour}/hour")
            if len(refs) >= 4 and left / len(refs) >= 0.5:
                reasons.append(f"leave_ratio:{left}/{len(refs)}")
            if len(refs) >= 20:
                reasons.append(f"volume:{len(refs)}")
            if reasons:
                flagged.append({
                    "referrer_id": referrer_id,
                    "referrals": len(refs),
                    "active": len(refs) - left,
                    "reasons": reasons,
                })
        flagged.sort(key=lambda row: (-len(row["reasons"]), -row["referrals"], row["referrer_id"]))
        return flagged
