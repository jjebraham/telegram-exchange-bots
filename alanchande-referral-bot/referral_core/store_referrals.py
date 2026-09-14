from __future__ import annotations

from datetime import datetime, timedelta

from .models import Campaign, UTC, iso_utc, parse_datetime, points_from_invites, utcnow


class ReferralMixin:
    def create_pending_referral(self, campaign: Campaign, joined_user_id: int, referrer_id: int,
                                joined_username: str | None, joined_first_name: str | None,
                                now: datetime | None = None) -> tuple[str, int]:
        """Reserve first-referrer attribution before the referred user joins the channel."""
        if joined_user_id == referrer_id:
            return "self", referrer_id
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            existing_referral = conn.execute(
                "SELECT referrer_id FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            ).fetchone()
            if existing_referral:
                return "existing_referral", int(existing_referral["referrer_id"])

            pending = conn.execute(
                "SELECT referrer_id FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            ).fetchone()
            if pending:
                conn.execute(
                    """UPDATE pending_referrals SET joined_username=?,joined_first_name=?,updated_at=?
                       WHERE campaign_id=? AND joined_user_id=?""",
                    (joined_username, joined_first_name, ts, campaign.id, joined_user_id),
                )
                return "existing", int(pending["referrer_id"])

            conn.execute(
                """INSERT INTO pending_referrals(
                       campaign_id,joined_user_id,referrer_id,joined_username,joined_first_name,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (campaign.id, joined_user_id, referrer_id, joined_username, joined_first_name, ts, ts),
            )
            return "created", referrer_id

    def pop_pending_referrer(self, campaign_id: int, joined_user_id: int) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT referrer_id FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "DELETE FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            )
            return int(row["referrer_id"])

    def pending_referrer(self, campaign_id: int, joined_user_id: int) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT referrer_id FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            ).fetchone()
        return int(row["referrer_id"]) if row else None

    def pending_reminder_candidates(self, campaign_id: int, older_than: datetime,
                                    limit: int = 100) -> list[dict]:
        cutoff = iso_utc(older_than)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.campaign_id,p.joined_user_id,p.referrer_id,p.joined_username,
                          p.joined_first_name,p.created_at
                   FROM pending_referrals p
                   LEFT JOIN pending_referral_reminders r
                     ON r.campaign_id=p.campaign_id AND r.joined_user_id=p.joined_user_id
                   WHERE p.campaign_id=? AND p.created_at<=? AND r.joined_user_id IS NULL
                   ORDER BY p.created_at ASC LIMIT ?""",
                (campaign_id, cutoff, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_pending_reminder_sent(self, campaign_id: int, joined_user_id: int,
                                   now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO pending_referral_reminders(campaign_id,joined_user_id,sent_at)
                   VALUES(?,?,?) ON CONFLICT(campaign_id,joined_user_id) DO NOTHING""",
                (campaign_id, joined_user_id, ts),
            )

    def referrer_for_joined(self, campaign_id: int, joined_user_id: int) -> int | None:
        """Return the permanent referrer already recorded for a referred account."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT referrer_id FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            ).fetchone()
        return int(row["referrer_id"]) if row else None

    def record_join(self, campaign: Campaign, joined_user_id: int, referrer_id: int,
                    joined_username: str | None, joined_first_name: str | None,
                    now: datetime | None = None) -> str:
        if joined_user_id == referrer_id:
            return "self"
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            ).fetchone()
            if existing:
                if existing["active"]:
                    return "duplicate"
                conn.execute(
                    """UPDATE referrals SET active=1,left_at=NULL,stay_since=?,
                       joined_username=?,joined_first_name=?,qualified_notified_at=NULL,updated_at=?
                       WHERE id=?""",
                    (ts, joined_username, joined_first_name, ts, existing["id"]),
                )
                return "reactivated"
            conn.execute(
                """INSERT INTO referrals(campaign_id,joined_user_id,referrer_id,joined_username,
                   joined_first_name,joined_at,stay_since,active,updated_at)
                   VALUES(?,?,?,?,?,?,?,1,?)""",
                (campaign.id, joined_user_id, referrer_id, joined_username,
                 joined_first_name, ts, ts, ts),
            )
            return "created"

    def reactivate_original(self, campaign_id: int, joined_user_id: int,
                            username: str | None, first_name: str | None,
                            now: datetime | None = None) -> int | None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            ).fetchone()
            if not row or row["active"]:
                return None
            conn.execute(
                """UPDATE referrals SET active=1,left_at=NULL,stay_since=?,joined_username=?,
                   joined_first_name=?,qualified_notified_at=NULL,updated_at=? WHERE id=?""",
                (ts, username, first_name, ts, row["id"]),
            )
            return row["referrer_id"]

    def mark_left(self, joined_user_id: int, now: datetime | None = None) -> int:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE referrals SET active=0,left_at=?,updated_at=?
                   WHERE joined_user_id=? AND active=1 AND campaign_id IN
                   (SELECT id FROM campaigns WHERE status IN ('active','closed'))""",
                (ts, ts, joined_user_id),
            )
            return cur.rowcount

    def campaign_counts(self, campaign: Campaign, referrer_id: int,
                        now: datetime | None = None) -> dict[str, int]:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            row = conn.execute(
                """SELECT
                   SUM(CASE WHEN active=1 AND stay_since<=? THEN 1 ELSE 0 END) AS qualified,
                   SUM(CASE WHEN active=1 AND stay_since>? THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS left_count,
                   COUNT(*) AS total
                   FROM referrals WHERE campaign_id=? AND referrer_id=?""",
                (cutoff, cutoff, campaign.id, referrer_id),
            ).fetchone()
        qualified = int(row["qualified"] or 0)
        return {
            "qualified": qualified,
            "pending": int(row["pending"] or 0),
            "left": int(row["left_count"] or 0),
            "total": int(row["total"] or 0),
            "points": points_from_invites(qualified, campaign.invites_per_point, campaign.max_points),
        }

    def referral_list(self, campaign: Campaign, referrer_id: int, limit: int = 15,
                      now: datetime | None = None) -> list[dict]:
        now_dt = (now or utcnow()).astimezone(UTC)
        cutoff = campaign.cutoff(now_dt)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT joined_user_id,joined_username,joined_first_name,stay_since,left_at,active
                   FROM referrals WHERE campaign_id=? AND referrer_id=?
                   ORDER BY id DESC LIMIT ?""",
                (campaign.id, referrer_id, max(1, limit)),
            ).fetchall()
        result = []
        for row in rows:
            stay_dt = parse_datetime(row["stay_since"])
            if not row["active"]:
                status, remaining = "left", 0
            elif stay_dt <= cutoff:
                status, remaining = "qualified", 0
            else:
                status = "pending"
                qualifies_at = stay_dt + timedelta(hours=campaign.min_stay_hours)
                remaining = max(0, int((qualifies_at - now_dt).total_seconds()))
            result.append({
                "user_id": row["joined_user_id"], "username": row["joined_username"],
                "first_name": row["joined_first_name"], "status": status,
                "remaining_seconds": remaining,
            })
        return result

    def qualified_referral_ids(self, campaign: Campaign,
                               now: datetime | None = None) -> list[int]:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT joined_user_id FROM referrals
                   WHERE campaign_id=? AND active=1 AND stay_since<=? ORDER BY joined_user_id""",
                (campaign.id, cutoff),
            ).fetchall()
        return [int(row["joined_user_id"]) for row in rows]

    def deactivate_referrals(self, campaign_id: int, joined_user_ids,
                             now: datetime | None = None) -> int:
        ids = sorted(set(int(x) for x in joined_user_ids))
        if not ids:
            return 0
        ts = iso_utc(now or utcnow())
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            cur = conn.execute(
                f"""UPDATE referrals SET active=0,left_at=?,updated_at=?
                    WHERE campaign_id=? AND joined_user_id IN ({placeholders})""",
                (ts, ts, campaign_id, *ids),
            )
            return cur.rowcount
