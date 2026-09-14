from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Campaign, SLUG_RE, UTC, iso_utc, utcnow
from .schema import SCHEMA


class ReferralDBBase:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @staticmethod
    def _campaign(row: sqlite3.Row | None) -> Campaign | None:
        if not row:
            return None
        return Campaign(
            id=row["id"], slug=row["slug"], name=row["name"],
            start_at=row["start_at"], end_at=row["end_at"], status=row["status"],
            invites_per_point=row["invites_per_point"], min_stay_hours=row["min_stay_hours"],
            max_points=row["max_points"], num_winners=row["num_winners"],
            prize_text=row["prize_text"],
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
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO campaigns(slug,name,start_at,end_at,status,invites_per_point,
                   min_stay_hours,max_points,num_winners,prize_text,created_at,updated_at)
                   VALUES(?,?,?,?,'draft',?,?,?,?,?,?,?)""",
                (slug, name.strip(), iso_utc(start), iso_utc(end), invites_per_point,
                 min_stay_hours, max_points, num_winners, prize_text.strip(), ts, ts),
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
            if row["status"] not in {"draft", "active"}:
                raise ValueError("only draft/active campaigns can be reconfigured")
            conn.execute(
                """UPDATE campaigns SET invites_per_point=?,min_stay_hours=?,max_points=?,
                   num_winners=?,updated_at=? WHERE slug=?""",
                (invites_per_point, min_stay_hours, max_points, num_winners, ts, slug),
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
            conn.execute("UPDATE campaigns SET status='active',updated_at=? WHERE slug=?", (ts, slug))
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
