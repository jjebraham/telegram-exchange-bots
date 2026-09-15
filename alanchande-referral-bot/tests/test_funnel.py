import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import ReferralDB

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


if __name__ == "__main__":
    unittest.main()
