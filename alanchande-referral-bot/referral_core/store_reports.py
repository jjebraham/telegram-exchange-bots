from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence

from .models import Campaign, entrant_snapshot, iso_utc, points_from_invites, utcnow


class ReportsMixin:
    def leaderboard(self, campaign: Campaign, limit: int = 10,
                    now: datetime | None = None) -> list[dict]:
        """Return a live leaderboard ranked by provisional/current score.

        Current score is based on all referrals that are still members now.
        Confirmed score keeps the retention requirement and is the only score
        used by ``current_entrants`` and the final draw.
        """
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
            result.append({
                "user_id": int(row["referrer_id"]),
                "active": active,
                "qualified": qualified,
                "current_points": points_from_invites(
                    active, campaign.invites_per_point, campaign.max_points
                ),
                "confirmed_points": points_from_invites(
                    qualified, campaign.invites_per_point, campaign.max_points
                ),
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

    def current_entrants(self, campaign: Campaign, now: datetime | None = None,
                         eligible_user_ids: set[int] | None = None) -> list[tuple[int, int]]:
        cutoff = iso_utc(campaign.cutoff(now))
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

    def entrant_user_ids(self, campaign: Campaign, now: datetime | None = None) -> list[int]:
        return [uid for uid, _ in self.current_entrants(campaign, now)]

    def participant_count(self, campaign_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM invite_links WHERE campaign_id=?", (campaign_id,)).fetchone()
        return int(row["n"])

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
        entrants = self.current_entrants(campaign, now)
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
            link = conn.execute("SELECT invite_link FROM invite_links WHERE campaign_id=? AND user_id=?", (campaign.id, user_id)).fetchone()
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
            conn.execute("UPDATE referrals SET qualified_notified_at=?,updated_at=? WHERE id=?", (ts, ts, referral_id))

    def save_draw(self, campaign: Campaign, seed: str, entrants: Sequence[tuple[int, int]],
                  winners: Sequence[int], verification_summary: str,
                  now: datetime | None = None) -> str:
        payload, digest = entrant_snapshot(entrants)
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM draws WHERE campaign_id=?", (campaign.id,)).fetchone():
                raise ValueError("campaign already has a recorded draw")
            conn.execute(
                """INSERT INTO draws(campaign_id,seed,entrants_json,winners_json,entrant_digest,
                   verification_summary,created_at) VALUES(?,?,?,?,?,?,?)""",
                (campaign.id, seed, payload, json.dumps(list(winners), separators=(",", ":")),
                 digest, verification_summary, ts),
            )
            conn.execute("UPDATE campaigns SET status='drawn',updated_at=? WHERE id=?", (ts, campaign.id))
        return digest

    def draw_for_campaign(self, campaign_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM draws WHERE campaign_id=?", (campaign_id,)).fetchone()
        return dict(row) if row else None
