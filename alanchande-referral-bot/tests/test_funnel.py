import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import ReferralDB
from telegram_bot.admin_handlers import _extended_funnel, _review_signals

UTC = timezone.utc


class FunnelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        self.campaign = self.db.create_campaign(
            "paeez1405",
            "Paeez 1405",
            self.now - timedelta(days=1),
            self.now + timedelta(days=30),
            "prizes",
            invites_per_point=2,
            min_stay_hours=168,
            max_points=20,
            num_winners=5,
        )
        self.db.activate_campaign("paeez1405", self.now)
        self.campaign = self.db.get_campaign("paeez1405")
        for uid, name in [(10, "Alice"), (20, "Bob"), (30, "Carol"), (40, "Dave")]:
            self.db.upsert_user(uid, None, name, now=self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_funnel_events_are_unique_per_source(self):
        self.db.track_funnel_event(self.campaign.id, 10, "bot_start", "bigchannel", self.now)
        self.db.track_funnel_event(self.campaign.id, 10, "bot_start", "bigchannel", self.now)
        self.db.track_funnel_event(self.campaign.id, 10, "bot_start", "organic", self.now)
        stats = self.db.funnel_stats(self.campaign, self.now)
        self.assertEqual(stats["bot_starts"], 1)
        sources = {row["source"]: row["count"] for row in stats["sources"]}
        self.assertEqual(sources, {"bigchannel": 1, "organic": 1})

    def test_funnel_combines_events_and_database_state(self):
        self.db.track_funnel_event(self.campaign.id, 20, "bot_start", "bigchannel", self.now)
        self.db.track_funnel_event(self.campaign.id, 30, "referral_open", "referral", self.now)
        self.db.save_invite_link(self.campaign.id, 20, "ref_1_owner", self.now)
        self.db.create_pending_referral(self.campaign, 30, 20, None, "Carol", self.now)
        self.db.record_join(self.campaign, 40, 20, None, "Dave", self.now)

        stats = self.db.funnel_stats(self.campaign, self.now)
        self.assertEqual(stats["bot_starts"], 1)
        self.assertEqual(stats["participants_with_links"], 1)
        self.assertEqual(stats["referral_opens"], 1)
        self.assertEqual(stats["referral_candidates"], 2)
        self.assertEqual(stats["joined_referrals"], 1)
        self.assertEqual(stats["active_referrals"], 1)
        self.assertEqual(stats["qualified_referrals"], 0)

    def test_extended_funnel_has_conversion_and_source_quality(self):
        start_at = self.now - timedelta(hours=2)
        link_at = self.now - timedelta(hours=1)
        open_at = self.now - timedelta(minutes=20)
        join_at = self.now - timedelta(minutes=18)

        self.db.track_funnel_event(self.campaign.id, 20, "bot_start", "bigchannel", start_at)
        self.db.track_funnel_event(self.campaign.id, 20, "entered_contest", "bigchannel", start_at)
        self.db.save_invite_link(self.campaign.id, 20, "ref_1_bob", link_at)
        self.db.track_funnel_event(self.campaign.id, 30, "referral_open", "referral", open_at)
        self.db.record_join(self.campaign, 30, 20, None, "Carol", join_at)

        metrics = _extended_funnel(self.db, self.campaign)
        self.assertEqual(metrics["open_to_join_pct"], 100.0)
        self.assertEqual(metrics["join_to_active_pct"], 100.0)
        self.assertEqual(metrics["first_referral_median_seconds"], 2520)
        self.assertEqual(len(metrics["source_funnel"]), 1)
        source = metrics["source_funnel"][0]
        self.assertEqual(source["source"], "bigchannel")
        self.assertEqual(source["starts"], 1)
        self.assertEqual(source["participants"], 1)
        self.assertEqual(source["joined"], 1)

    def test_review_signals_include_low_secondary_activity(self):
        referrer = 20
        for index in range(10):
            uid = 1000 + index
            joined_at = self.now - timedelta(hours=20 - index * 2)
            self.db.upsert_user(uid, None, f"U{uid}", now=joined_at)
            self.db.record_join(
                self.campaign, uid, referrer, None, f"U{uid}", joined_at
            )

        rows = _review_signals(self.db, self.campaign, self.db.fraud_flags(self.campaign))
        row = next(item for item in rows if item["referrer_id"] == referrer)
        self.assertTrue(any(reason.startswith("low_secondary_activity:") for reason in row["reasons"]))
        self.assertEqual(row["secondary_participants"], 0)


if __name__ == "__main__":
    unittest.main()
