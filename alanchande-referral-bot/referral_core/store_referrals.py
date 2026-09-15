from __future__ import annotations

import json
from datetime import datetime, timedelta

from .models import Campaign, UTC, iso_utc, parse_datetime, points_from_invites, utcnow


class ReferralMixin:
    @staticmethod
    def _event(conn, campaign_id: int, joined_user_id: int, referrer_id: int | None,
               event_type: str, event_at: str, details: dict | None = None) -> None:
        conn.execute(
            """INSERT INTO referral_events(
                   campaign_id,joined_user_id,referrer_id,event_type,event_at,details_json
               ) VALUES(?,?,?,?,?,?)""",
            (
                campaign_id, joined_user_id, referrer_id, event_type, event_at,
                json.dumps(details or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )

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
            self._event(conn, campaign.id, joined_user_id, referrer_id, "pending_created", ts)
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

    def pending_referral_count(self, campaign_id: int, referrer_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_referrals WHERE campaign_id=? AND referrer_id=?",
                (campaign_id, referrer_id),
            ).fetchone()
        return int(row["n"] or 0)

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

    def pending_reconciliation_candidates(self, campaign_id: int, limit: int = 200) -> list[dict]:
        """All unresolved pending referrals, including users already reminded."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT campaign_id,joined_user_id,referrer_id,joined_username,
                          joined_first_name,created_at
                   FROM pending_referrals WHERE campaign_id=?
                   ORDER BY created_at ASC LIMIT ?""",
                (campaign_id, max(1, limit)),
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

    def participant_welcome_sent(self, campaign_id: int, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM participant_welcomes WHERE campaign_id=? AND user_id=?",
                (campaign_id, user_id),
            ).fetchone()
        return row is not None

    def mark_participant_welcome_sent(self, campaign_id: int, user_id: int,
                                      now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO participant_welcomes(campaign_id,user_id,sent_at)
                   VALUES(?,?,?) ON CONFLICT(campaign_id,user_id) DO NOTHING""",
                (campaign_id, user_id, ts),
            )

    def referrer_for_joined(self, campaign_id: int, joined_user_id: int) -> int | None:
        """Return the permanent referrer already recorded for a referred account."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT referrer_id FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign_id, joined_user_id),
            ).fetchone()
        return int(row["referrer_id"]) if row else None

    def finalize_pending_join(self, campaign: Campaign, joined_user_id: int,
                              joined_username: str | None, joined_first_name: str | None,
                              now: datetime | None = None) -> tuple[str, int | None]:
        """Atomically consume pending attribution and create/reactivate one referral row."""
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                "SELECT referrer_id FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            ).fetchone()
            existing = conn.execute(
                "SELECT * FROM referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            ).fetchone()

            if pending is None:
                if existing is not None:
                    return "already_recorded", int(existing["referrer_id"])
                return "missing", None

            referrer_id = int(pending["referrer_id"])
            if joined_user_id == referrer_id:
                conn.execute(
                    "DELETE FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                    (campaign.id, joined_user_id),
                )
                return "self", referrer_id

            if existing is not None:
                permanent_referrer = int(existing["referrer_id"])
                conn.execute(
                    "DELETE FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                    (campaign.id, joined_user_id),
                )
                if existing["active"]:
                    return "duplicate", permanent_referrer
                conn.execute(
                    """UPDATE referrals SET active=1,left_at=NULL,stay_since=?,
                       joined_username=?,joined_first_name=?,qualified_notified_at=NULL,updated_at=?
                       WHERE id=?""",
                    (ts, joined_username, joined_first_name, ts, existing["id"]),
                )
                self._event(
                    conn, campaign.id, joined_user_id, permanent_referrer,
                    "rejoined", ts, {"source": "pending_finalize"},
                )
                return "reactivated", permanent_referrer

            conn.execute(
                """INSERT INTO referrals(campaign_id,joined_user_id,referrer_id,joined_username,
                   joined_first_name,joined_at,stay_since,active,updated_at)
                   VALUES(?,?,?,?,?,?,?,1,?)""",
                (campaign.id, joined_user_id, referrer_id, joined_username,
                 joined_first_name, ts, ts, ts),
            )
            conn.execute(
                "DELETE FROM pending_referrals WHERE campaign_id=? AND joined_user_id=?",
                (campaign.id, joined_user_id),
            )
            self._event(conn, campaign.id, joined_user_id, referrer_id, "joined", ts)
            return "created", referrer_id

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
                permanent_referrer = int(existing["referrer_id"])
                conn.execute(
                    """UPDATE referrals SET active=1,left_at=NULL,stay_since=?,
                       joined_username=?,joined_first_name=?,qualified_notified_at=NULL,updated_at=?
                       WHERE id=?""",
                    (ts, joined_username, joined_first_name, ts, existing["id"]),
                )
                self._event(conn, campaign.id, joined_user_id, permanent_referrer, "rejoined", ts)
                return "reactivated"
            conn.execute(
                """INSERT INTO referrals(campaign_id,joined_user_id,referrer_id,joined_username,
                   joined_first_name,joined_at,stay_since,active,updated_at)
                   VALUES(?,?,?,?,?,?,?,1,?)""",
                (campaign.id, joined_user_id, referrer_id, joined_username,
                 joined_first_name, ts, ts, ts),
            )
            self._event(conn, campaign.id, joined_user_id, referrer_id, "joined", ts)
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
            self._event(conn, campaign_id, joined_user_id, int(row["referrer_id"]), "rejoined", ts)
            return int(row["referrer_id"])

    def mark_left(self, joined_user_id: int, now: datetime | None = None) -> int:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,campaign_id,referrer_id FROM referrals
                   WHERE joined_user_id=? AND active=1 AND campaign_id IN
                   (SELECT id FROM campaigns WHERE status IN ('active','closed'))""",
                (joined_user_id,),
            ).fetchall()
            if not rows:
                return 0
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE referrals SET active=0,left_at=?,updated_at=? WHERE id IN ({placeholders})",
                (ts, ts, *ids),
            )
            for row in rows:
                self._event(
                    conn, int(row["campaign_id"]), joined_user_id,
                    int(row["referrer_id"]), "left", ts,
                )
            return len(rows)

    def active_referrals_for_reconciliation(self, campaign_id: int, limit: int = 500) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,joined_user_id,referrer_id,joined_username,joined_first_name
                   FROM referrals WHERE campaign_id=? AND active=1 ORDER BY id LIMIT ?""",
                (campaign_id, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def campaign_counts(self, campaign: Campaign, referrer_id: int,
                        now: datetime | None = None) -> dict[str, int]:
        cutoff = iso_utc(campaign.cutoff(now))
        with self.connect() as conn:
            row = conn.execute(
                """SELECT
                   SUM(CASE WHEN active=1 AND stay_since<=? THEN 1 ELSE 0 END) AS qualified,
                   SUM(CASE WHEN active=1 AND stay_since>? THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active_count,
                   SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS left_count,
                   COUNT(*) AS total
                   FROM referrals WHERE campaign_id=? AND referrer_id=?""",
                (cutoff, cutoff, campaign.id, referrer_id),
            ).fetchone()
        qualified = int(row["qualified"] or 0)
        active = int(row["active_count"] or 0)
        confirmed_points = points_from_invites(
            qualified, campaign.invites_per_point, campaign.max_points
        )
        current_points = points_from_invites(
            active, campaign.invites_per_point, campaign.max_points
        )
        return {
            "qualified": qualified,
            "pending": int(row["pending"] or 0),
            "active": active,
            "left": int(row["left_count"] or 0),
            "total": int(row["total"] or 0),
            "points": confirmed_points,
            "confirmed_points": confirmed_points,
            "current_points": current_points,
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
                "can_qualify_by_draw": stay_dt <= campaign.final_qualification_cutoff,
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
            rows = conn.execute(
                f"SELECT joined_user_id,referrer_id FROM referrals WHERE campaign_id=? AND joined_user_id IN ({placeholders}) AND active=1",
                (campaign_id, *ids),
            ).fetchall()
            cur = conn.execute(
                f"""UPDATE referrals SET active=0,left_at=?,updated_at=?
                    WHERE campaign_id=? AND joined_user_id IN ({placeholders}) AND active=1""",
                (ts, ts, campaign_id, *ids),
            )
            for row in rows:
                self._event(
                    conn, campaign_id, int(row["joined_user_id"]), int(row["referrer_id"]),
                    "deactivated_verification", ts,
                )
            return cur.rowcount
