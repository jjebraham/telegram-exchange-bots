import sqlite3
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram_bot.reminders import _early_share_nudge_candidates


class TestEarlyShareOpenEligibility(unittest.TestCase):

    def test_only_inactive_link_holder_is_eligible(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row

        conn.executescript("""
            CREATE TABLE invite_links (
                campaign_id INTEGER,
                user_id INTEGER,
                invite_link TEXT,
                created_at TEXT
            );

            CREATE TABLE funnel_events (
                campaign_id INTEGER,
                user_id INTEGER,
                event_type TEXT
            );

            CREATE TABLE pending_referrals (
                campaign_id INTEGER,
                referrer_id INTEGER
            );

            CREATE TABLE referrals (
                campaign_id INTEGER,
                referrer_id INTEGER
            );
        """)

        for uid in range(101, 106):
            conn.execute(
                "INSERT INTO invite_links VALUES (?, ?, ?, ?)",
                (
                    6,
                    uid,
                    f"https://t.me/testbot?start={uid}",
                    "2026-09-20T00:00:00+00:00",
                ),
            )
            conn.execute(
                "INSERT INTO funnel_events VALUES "
                "(6, ?, 'entered_contest')",
                (uid,),
            )

        # 101: link already opened
        conn.execute(
            "INSERT INTO funnel_events VALUES "
            "(6, 101, 'referral_open_received')"
        )

        # 102: link exists, no referral activity

        # 103: pending referral
        conn.execute(
            "INSERT INTO pending_referrals VALUES (6, 103)"
        )

        # 104: existing referral
        conn.execute(
            "INSERT INTO referrals VALUES (6, 104)"
        )

        # 105: already received the reminder
        conn.execute(
            "INSERT INTO funnel_events VALUES "
            "(6, 105, 'nudge_early_share_sent')"
        )

        conn.commit()

        db = SimpleNamespace(connect=lambda: conn)

        rows = _early_share_nudge_candidates(
            db,
            6,
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )

        self.assertEqual(
            [int(row["user_id"]) for row in rows],
            [102],
        )


if __name__ == "__main__":
    unittest.main()
