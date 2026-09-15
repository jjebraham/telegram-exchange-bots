from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .models import (
    Campaign,
    SLUG_RE,
    UTC,
    default_draw_at,
    iso_utc,
    parse_datetime,
    utcnow,
)
from .schema import SCHEMA

ISTANBUL = timezone(timedelta(hours=3))


class ReferralDBBase:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Small additive migrations for existing production SQLite databases."""
        if not self._has_column(conn, "campaigns", "draw_at"):
            conn.execute("ALTER TABLE campaigns ADD COLUMN draw_at TEXT")
        if not self._has_column(conn, "campaigns", "rules_locked_at"):
            conn.execute("ALTER TABLE campaigns ADD COLUMN rules_locked_at TEXT")
        if not self._has_column(conn, "campaigns", "rules_version"):
            conn.execute("ALTER TABLE campaigns ADD COLUMN rules_version INTEGER NOT NULL DEFAULT 1")
        if not self._has_column(conn, "draws", "seed_source"):
            conn.execute("ALTER TABLE draws ADD COLUMN seed_source TEXT NOT NULL DEFAULT ''")
        if not self._has_column(conn, "draws", "reserves_json"):
            conn.execute("ALTER TABLE draws ADD COLUMN reserves_json TEXT NOT NULL DEFAULT '[]'")

        rows = conn.execute(
            "SELECT id,end_at,status,updated_at FROM campaigns WHERE draw_at IS NULL OR draw_at=''"
        ).fetchall()
        for row in rows:
            draw_at = default_draw_at(parse_datetime(row["end_at"]))
            locked_at = row["updated_at"] if row["status"] in {"active", "closed", "drawn"} else None
            conn.execute(
                """UPDATE campaigns SET draw_at=?, rules_locked_at=COALESCE(rules_locked_at,?)
                   WHERE id=?""",
                (iso_utc(draw_at), locked_at, row["id"]),
            )

        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version,applied_at) VALUES(3,?)",
            (iso_utc(utcnow()),),
        )

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _campaign(row: sqlite3.Row | None) -> Campaign | None:
        if not row:
            return None
        draw_at = row["draw_at"] if "draw_at" in row.keys() and row["draw_at"] else iso_utc(
            default_draw_at(parse_datetime(row["end_at"]))
        )
        return Campaign(
            id=row["id"], slug=row["slug"], name=row["name"],
            start_at=row["start_at"], end_at=row["end_at"], draw_at=draw_at,
            status=row["status"],
            invites_per_point=row["invites_per_point"], min_stay_hours=row["min_stay_hours"],
            max_points=row["max_points"], num_winners=row["num_winners"],
            prize_text=row["prize_text"],
            rules_locked_at=row["rules_locked_at"] if "rules_locked_at" in row.keys() else None,
            rules_version=int(row["rules_version"] if "rules_version" in row.keys() else 1),
        )

    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    last_name: str | None = None, now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO users(user_id,username,first_name,last_name,created_at,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username, first_name=excluded.first_name,
                   last_name=excluded.last_name, updated_at=excluded.updated_at""",
                (user_id, username, first_name, last_name, ts, ts),
            )

    def create_campaign(self, slug: str, name: str, start_at: datetime, end_at: datetime,
                        prize_text: str, invites_per_point: int = 2,
                        min_stay_hours: int = 168, max_points: int = 20,
                        num_winners: int = 5) -> Campaign:
        slug = slug.strip().lower()
        if not SLUG_RE.fullmatch(slug):
            raise ValueError("slug must be 2-40 chars: lowercase letters, numbers, _ or -")
        if not name.strip():
            raise ValueError("campaign name is required")
        start, end = start_at.astimezone(UTC), end_at.astimezone(UTC)
        if end <= start:
            raise ValueError("campaign end must be after start")
        if invites_per_point < 1 or min_stay_hours < 0 or max_points < 0 or num_winners < 1:
            raise ValueError("invalid campaign scoring values")
        ts = iso_utc(utcnow())
        draw_at = default_draw_at(end)
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO campaigns(slug,name,start_at,end_at,draw_at,status,invites_per_point,
                   min_stay_hours,max_points,num_winners,prize_text,rules_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,'draft',?,?,?,?,?,1,?,?)""",
                (slug, name.strip(), iso_utc(start), iso_utc(end), iso_utc(draw_at),
                 invites_per_point, min_stay_hours, max_points, num_winners,
                 prize_text.strip(), ts, ts),
            )
            row = conn.execute("SELECT * FROM campaigns WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._campaign(row)  # type: ignore[return-value]

    def configure_campaign(self, slug: str, invites_per_point: int, min_stay_hours: int,
                           max_points: int, num_winners: int) -> Campaign:
        if invites_per_point < 1 or min_stay_hours < 0 or max_points < 0 or num_winners < 1:
            raise ValueError("invalid campaign scoring values")
        ts = iso_utc(utcnow())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
            if not row:
                raise KeyError(slug)
            if row["status"] != "draft":
                raise ValueError("campaign scoring rules are locked after activation")
            conn.execute(
                """UPDATE campaigns SET invites_per_point=?,min_stay_hours=?,max_points=?,
                   num_winners=?,rules_version=rules_version+1,updated_at=? WHERE slug=?""",
                (invites_per_point, min_stay_hours, max_points, num_winners, ts, slug),
            )
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        return self._campaign(row)  # type: ignore[return-value]

    def set_campaign_draw_at(self, slug: str, draw_at: datetime) -> Campaign:
        ts = iso_utc(utcnow())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
            if not row:
                raise KeyError(slug)
            if row["status"] != "draft":
                raise ValueError("draw time is locked after campaign activation")
            if draw_at.astimezone(UTC) <= parse_datetime(row["end_at"]):
                raise ValueError("draw time must be after campaign end")
            conn.execute(
                "UPDATE campaigns SET draw_at=?,rules_version=rules_version+1,updated_at=? WHERE slug=?",
                (iso_utc(draw_at), ts, slug),
            )
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        return self._campaign(row)  # type: ignore[return-value]

    def get_campaign(self, slug: str) -> Campaign | None:
        with self.connect() as conn:
            return self._campaign(conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone())

    def list_campaigns(self, limit: int = 20) -> list[Campaign]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT ?", (max(1, limit),)).fetchall()
        return [self._campaign(row) for row in rows if row]  # type: ignore[list-item]

    def live_campaign(self, now: datetime | None = None) -> Campaign | None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            row = conn.execute(
                """SELECT * FROM campaigns WHERE status='active' AND start_at<=? AND end_at>?
                   ORDER BY id DESC LIMIT 1""", (ts, ts)
            ).fetchone()
        return self._campaign(row)

    def activate_campaign(self, slug: str, now: datetime | None = None) -> Campaign:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
            if not row:
                raise KeyError(slug)
            if row["status"] == "drawn":
                raise ValueError("drawn campaign cannot be reactivated")
            conn.execute("UPDATE campaigns SET status='closed',updated_at=? WHERE status='active' AND slug<>?", (ts, slug))
            conn.execute(
                """UPDATE campaigns SET status='active',rules_locked_at=COALESCE(rules_locked_at,?),
                   updated_at=? WHERE slug=?""",
                (ts, ts, slug),
            )
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        return self._campaign(row)  # type: ignore[return-value]

    def close_campaign(self, slug: str, now: datetime | None = None) -> Campaign:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
            if not row:
                raise KeyError(slug)
            if row["status"] != "drawn":
                conn.execute("UPDATE campaigns SET status='closed',updated_at=? WHERE slug=?", (ts, slug))
                row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        return self._campaign(row)  # type: ignore[return-value]

    def log_admin_action(self, campaign_id: int | None, admin_user_id: int, action: str,
                         details: dict | None = None, now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        payload = json.dumps(details or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO admin_audit_log(campaign_id,admin_user_id,action,details_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (campaign_id, int(admin_user_id), action[:64], payload, ts),
            )

    def capture_daily_metrics(self, campaign: Campaign, now: datetime | None = None) -> dict:
        """Upsert one Istanbul-calendar-day analytics snapshot for trend reporting."""
        at = (now or utcnow()).astimezone(UTC)
        funnel = self.funnel_stats(campaign, at)  # type: ignore[attr-defined]
        admin = self.admin_stats(campaign, at)  # type: ignore[attr-defined]
        with self.connect() as conn:
            continued = conn.execute(
                """SELECT COUNT(DISTINCT r.joined_user_id) AS n
                   FROM referrals r JOIN invite_links il
                     ON il.campaign_id=r.campaign_id AND il.user_id=r.joined_user_id
                   WHERE r.campaign_id=?""",
                (campaign.id,),
            ).fetchone()
            refs = conn.execute(
                """SELECT joined_user_id,joined_at,left_at FROM referrals
                   WHERE campaign_id=?""",
                (campaign.id,),
            ).fetchall()
            left_rows = conn.execute(
                """SELECT joined_user_id,MIN(event_at) AS first_left FROM referral_events
                   WHERE campaign_id=? AND event_type='left' GROUP BY joined_user_id""",
                (campaign.id,),
            ).fetchall()

        first_left = {
            int(row["joined_user_id"]): parse_datetime(row["first_left"])
            for row in left_rows if row["first_left"]
        }

        def retention(hours: int) -> tuple[float | None, int]:
            retained = eligible = 0
            horizon = timedelta(hours=hours)
            for row in refs:
                joined = parse_datetime(row["joined_at"])
                target = joined + horizon
                if at < target:
                    continue
                eligible += 1
                left = first_left.get(int(row["joined_user_id"]))
                if left is None and row["left_at"]:
                    left = parse_datetime(row["left_at"])
                if left is None or left >= target:
                    retained += 1
            return ((round(retained * 100.0 / eligible, 1) if eligible else None), eligible)

        d1, d1_n = retention(24)
        d7, d7_n = retention(168)
        participants = int(funnel["participants_with_links"])
        referred_participants = int(continued["n"] or 0)
        metrics = {
            "bot_starts": int(funnel["bot_starts"]),
            "participants": participants,
            "referral_opens": int(funnel["referral_opens"]),
            "joined": int(funnel["joined_referrals"]),
            "active": int(funnel["active_referrals"]),
            "qualified": int(funnel["qualified_referrals"]),
            "tickets": int(admin["tickets"]),
            "k_factor_proxy": round(referred_participants / participants, 3) if participants else 0.0,
            "d1_retention_pct": d1,
            "d1_sample": d1_n,
            "d7_retention_pct": d7,
            "d7_sample": d7_n,
        }
        date_key = at.astimezone(ISTANBUL).date().isoformat()
        ts = iso_utc(at)
        payload = json.dumps(metrics, sort_keys=True, separators=(",", ":"))
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO campaign_daily_metrics(
                       campaign_id,snapshot_date,metrics_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?)
                   ON CONFLICT(campaign_id,snapshot_date) DO UPDATE SET
                     metrics_json=excluded.metrics_json,updated_at=excluded.updated_at""",
                (campaign.id, date_key, payload, ts, ts),
            )
        return {"snapshot_date": date_key, **metrics}

    def daily_metrics(self, campaign_id: int, limit: int = 14) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT snapshot_date,metrics_json,updated_at FROM campaign_daily_metrics
                   WHERE campaign_id=? ORDER BY snapshot_date DESC LIMIT ?""",
                (campaign_id, max(1, limit)),
            ).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["metrics_json"])
            item.update({"snapshot_date": row["snapshot_date"], "updated_at": row["updated_at"]})
            result.append(item)
        return result

    def zero_referral_nudge_candidates(self, campaign_id: int, older_than: datetime,
                                       limit: int = 100) -> list[dict]:
        cutoff = iso_utc(older_than)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT il.user_id,il.invite_link,il.created_at
                   FROM invite_links il
                   WHERE il.campaign_id=? AND il.created_at<=?
                     AND NOT EXISTS (
                       SELECT 1 FROM referrals r
                       WHERE r.campaign_id=il.campaign_id AND r.referrer_id=il.user_id
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM pending_referrals p
                       WHERE p.campaign_id=il.campaign_id AND p.referrer_id=il.user_id
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM funnel_events f
                       WHERE f.campaign_id=il.campaign_id AND f.user_id=il.user_id
                         AND f.event_type='nudge_zero_referral_sent'
                     )
                   ORDER BY il.created_at ASC LIMIT ?""",
                (campaign_id, cutoff, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def promo_abandon_nudge_candidates(self, campaign_id: int, older_than: datetime,
                                       limit: int = 100) -> list[dict]:
        cutoff = iso_utc(older_than)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT f.user_id,MIN(f.created_at) AS started_at,MIN(f.source) AS source
                   FROM funnel_events f
                   WHERE f.campaign_id=? AND f.event_type='bot_start' AND f.created_at<=?
                     AND f.source NOT IN ('','organic','referral','existing_member')
                     AND NOT EXISTS (
                       SELECT 1 FROM invite_links il
                       WHERE il.campaign_id=f.campaign_id AND il.user_id=f.user_id
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM funnel_events sent
                       WHERE sent.campaign_id=f.campaign_id AND sent.user_id=f.user_id
                         AND sent.event_type='nudge_promo_abandon_sent'
                     )
                   GROUP BY f.user_id ORDER BY started_at ASC LIMIT ?""",
                (campaign_id, cutoff, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def notification_gate(self, campaign_id: int, user_id: int, max_messages: int,
                          window_seconds: int, now: datetime | None = None) -> bool:
        """Allow a bounded number of automated event messages per participant/window."""
        at = (now or utcnow()).astimezone(UTC)
        ts = iso_utc(at)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM notification_throttle WHERE campaign_id=? AND user_id=?",
                (campaign_id, user_id),
            ).fetchone()
            if not row or (at - parse_datetime(row["window_started_at"])).total_seconds() >= window_seconds:
                conn.execute(
                    """INSERT INTO notification_throttle(
                           campaign_id,user_id,window_started_at,sent_count,suppressed_count,updated_at
                       ) VALUES(?,?,?,1,0,?)
                       ON CONFLICT(campaign_id,user_id) DO UPDATE SET
                         window_started_at=excluded.window_started_at,sent_count=1,
                         suppressed_count=0,updated_at=excluded.updated_at""",
                    (campaign_id, user_id, ts, ts),
                )
                return True
            if int(row["sent_count"]) < max(1, max_messages):
                conn.execute(
                    """UPDATE notification_throttle SET sent_count=sent_count+1,updated_at=?
                       WHERE campaign_id=? AND user_id=?""",
                    (ts, campaign_id, user_id),
                )
                return True
            conn.execute(
                """UPDATE notification_throttle SET suppressed_count=suppressed_count+1,updated_at=?
                   WHERE campaign_id=? AND user_id=?""",
                (ts, campaign_id, user_id),
            )
            return False

    def notification_summaries_due(self, campaign_id: int, older_than: datetime,
                                   limit: int = 100) -> list[dict]:
        cutoff = iso_utc(older_than)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT user_id,suppressed_count FROM notification_throttle
                   WHERE campaign_id=? AND suppressed_count>0 AND updated_at<=?
                   ORDER BY updated_at ASC LIMIT ?""",
                (campaign_id, cutoff, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_notification_summary(self, campaign_id: int, user_id: int,
                                   now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """UPDATE notification_throttle SET window_started_at=?,sent_count=0,
                   suppressed_count=0,updated_at=? WHERE campaign_id=? AND user_id=?""",
                (ts, ts, campaign_id, user_id),
            )

    def set_maintenance_status(self, name: str, ok: bool, details: dict | None = None,
                               error: str | None = None, now: datetime | None = None) -> None:
        ts = iso_utc(now or utcnow())
        payload = json.dumps(details or {}, sort_keys=True, separators=(",", ":"))
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM maintenance_status WHERE name=?", (name,)).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO maintenance_status(
                           name,last_ok_at,last_error_at,last_error,details_json,updated_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (name, ts if ok else None, None if ok else ts,
                     None if ok else (error or "unknown error")[:500], payload, ts),
                )
            elif ok:
                conn.execute(
                    """UPDATE maintenance_status SET last_ok_at=?,last_error=NULL,
                       details_json=?,updated_at=? WHERE name=?""",
                    (ts, payload, ts, name),
                )
            else:
                conn.execute(
                    """UPDATE maintenance_status SET last_error_at=?,last_error=?,
                       details_json=?,updated_at=? WHERE name=?""",
                    (ts, (error or "unknown error")[:500], payload, ts, name),
                )

    def maintenance_statuses(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM maintenance_status ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def pending_referrals_total(self, campaign_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_referrals WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return int(row["n"] or 0)

    def get_invite_link(self, campaign_id: int, user_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT invite_link FROM invite_links WHERE campaign_id=? AND user_id=?", (campaign_id, user_id)).fetchone()
        return row["invite_link"] if row else None

    def save_invite_link(self, campaign_id: int, user_id: int, invite_link: str,
                         now: datetime | None = None) -> str:
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO invite_links(campaign_id,user_id,invite_link,created_at)
                   VALUES(?,?,?,?) ON CONFLICT(campaign_id,user_id) DO NOTHING""",
                (campaign_id, user_id, invite_link, ts),
            )
            row = conn.execute("SELECT invite_link FROM invite_links WHERE campaign_id=? AND user_id=?", (campaign_id, user_id)).fetchone()
        if not row:
            raise RuntimeError("failed to persist invite link")
        return row["invite_link"]

    def replace_invite_link(self, campaign_id: int, user_id: int, invite_link: str,
                            now: datetime | None = None) -> str:
        """Replace a legacy channel invite with a bot deep-link payload."""
        ts = iso_utc(now or utcnow())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO invite_links(campaign_id,user_id,invite_link,created_at)
                   VALUES(?,?,?,?) ON CONFLICT(campaign_id,user_id) DO UPDATE SET
                   invite_link=excluded.invite_link, created_at=excluded.created_at""",
                (campaign_id, user_id, invite_link, ts),
            )
        return invite_link

    def invite_owner(self, invite_link: str) -> tuple[Campaign, int] | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT c.*,il.user_id AS referrer_id FROM invite_links il
                   JOIN campaigns c ON c.id=il.campaign_id WHERE il.invite_link=?""",
                (invite_link,),
            ).fetchone()
        if not row:
            return None
        return self._campaign(row), row["referrer_id"]  # type: ignore[return-value]
