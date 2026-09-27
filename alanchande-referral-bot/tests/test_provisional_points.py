import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import ReferralDB

UTC = timezone.utc


class ProvisionalPointsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
        campaign = self.db.create_campaign(
            "paeeztest",
            "Paeez Test",
            self.now - timedelta(days=1),
            self.now + timedelta(days=30),
            "prizes",
            invites_per_point=2,
            min_stay_hours=168,
            max_points=20,
            num_winners=5,
        )
        self.db.activate_campaign(campaign.slug, self.now)
        self.campaign = self.db.get_campaign(campaign.slug)
        self.db.upsert_user(10, "inviter", "Inviter", now=self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_referrals_give_current_points_before_confirmation(self):
        for uid in (101, 102, 103):
            self.db.record_join(
                self.campaign, uid, 10, f"u{uid}", f"U{uid}", self.now
            )

        counts = self.db.campaign_counts(self.campaign, 10, self.now)
        self.assertEqual(counts["active"], 3)
        self.assertEqual(counts["pending"], 3)
        self.assertEqual(counts["qualified"], 0)
        self.assertEqual(counts["current_points"], 1)
        self.assertEqual(counts["confirmed_points"], 0)
        self.assertEqual(counts["points"], 0)

        self.db.mark_left(101, self.now + timedelta(minutes=1))
        counts = self.db.campaign_counts(self.campaign, 10, self.now + timedelta(minutes=1))
        self.assertEqual(counts["active"], 2)
        self.assertEqual(counts["current_points"], 1)

        self.db.mark_left(102, self.now + timedelta(minutes=2))
        counts = self.db.campaign_counts(self.campaign, 10, self.now + timedelta(minutes=2))
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["current_points"], 0)
        self.assertEqual(counts["confirmed_points"], 0)


if __name__ == "__main__":
    unittest.main()
