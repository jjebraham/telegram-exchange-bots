from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.share_activation import (
    record_referral_open_received,
    sharing_source_performance,
    zero_open_nudge_candidates,
)


class TinyDB:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def track_funnel_event(self, campaign_id, user_id, event_type, source):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO funnel_events(campaign_id,user_id,event_type,source,created_at) VALUES(?,?,?,?,?)",
                (campaign_id, user_id, event_type, source, "2026-09-17T08:00:00+00:00"),
            )


class RecorderDB:
    def __init__(self):
        self.events = []

    def track_funnel_event(self, campaign_id, user_id, event_type, source):
        self.events.append((campaign_id, user_id, event_type, source))


class ShareActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TinyDB(str(Path(self.tmp.name) / "test.sqlite"))
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE funnel_events (
                    campaign_id INTEGER,
                    user_id INTEGER,
                    event_type TEXT,
                    source TEXT,
                    created_at TEXT
                );
                CREATE TABLE invite_links (
                    campaign_id INTEGER,
                    user_id INTEGER,
                    created_at TEXT
                );
                CREATE TABLE pending_referrals (
                    campaign_id INTEGER,
                    joined_user_id INTEGER,
                    referrer_id INTEGER
                );
                CREATE TABLE referrals (
                    campaign_id INTEGER,
                    joined_user_id INTEGER,
                    referrer_id INTEGER
                );
                """
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, user_id, event_type, source="organic", when="2026-09-17T07:00:00+00:00"):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO funnel_events VALUES(?,?,?,?,?)",
                (1, user_id, event_type, source, when),
            )

    def _link(self, user_id, when="2026-09-17T06:00:00+00:00"):
        with self.db.connect() as conn:
            conn.execute("INSERT INTO invite_links VALUES(?,?,?)", (1, user_id, when))

    def test_open_received_is_stored_on_referrer_and_self_open_is_ignored(self):
        db = RecorderDB()
        record_referral_open_received(db, 1, 10, 20)
        record_referral_open_received(db, 1, 10, 10)
        self.assertEqual(
            db.events,
            [(1, 10, "referral_open_received", "candidate:20")],
        )

    def test_zero_open_nudge_excludes_real_or_historical_downstream_activity(self):
        cutoff = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
        for uid in (1, 2, 3, 4):
            self._link(uid)
            self._event(uid, "entered_contest")

        self._event(2, "referral_open_received", "candidate:200")
        with self.db.connect() as conn:
            conn.execute("INSERT INTO pending_referrals VALUES(?,?,?)", (1, 300, 3))
        self._event(4, "nudge_early_share_sent")

        rows = zero_open_nudge_candidates(self.db, 1, cutoff, limit=100)
        self.assertEqual([row["user_id"] for row in rows], [1])

    def test_sharing_report_counts_unique_holders_and_historical_fallback(self):
        self._event(1, "bot_start", "referral", "2026-09-17T05:00:00+00:00")
        self._event(2, "bot_start", "mainchannel_b", "2026-09-17T05:00:00+00:00")
        self._link(1, "2026-09-17T06:00:00+00:00")
        self._link(2, "2026-09-17T06:00:00+00:00")

        self._event(1, "referral_open_received", "candidate:101", "2026-09-17T06:30:00+00:00")
        self._event(101, "referral_open", "referral", "2026-09-17T06:30:00+00:00")
        self._event(102, "referral_open", "referral", "2026-09-17T06:20:00+00:00")
        with self.db.connect() as conn:
            conn.execute("INSERT INTO referrals VALUES(?,?,?)", (1, 101, 1))
            conn.execute("INSERT INTO pending_referrals VALUES(?,?,?)", (1, 102, 2))

        report = sharing_source_performance(self.db, SimpleNamespace(id=1))
        rows = {row["source"]: row for row in report["rows"]}

        referral = rows["referral"]
        self.assertEqual(referral["link_holders"], 1)
        self.assertEqual(referral["holders_with_open"], 1)
        self.assertEqual(referral["holders_with_join"], 1)
        self.assertEqual(referral["unique_openers"], 1)
        self.assertEqual(referral["median_first_open_minutes"], 30.0)

        main = rows["mainchannel_b"]
        self.assertEqual(main["link_holders"], 1)
        self.assertEqual(main["holders_with_open"], 1)
        self.assertEqual(main["holders_with_candidate"], 1)
        self.assertEqual(main["holders_with_join"], 0)
        self.assertEqual(main["median_first_open_minutes"], 20.0)


if __name__ == "__main__":
    unittest.main()
