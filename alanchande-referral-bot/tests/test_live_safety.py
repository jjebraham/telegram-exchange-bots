import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import ReferralDB

UTC = timezone.utc


class LiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 15, 6, 0, tzinfo=UTC)
        self.campaign = self.db.create_campaign(
            "paeez1405",
            "پاییز ۱۴۰۵",
            self.now,
            datetime(2026, 10, 15, 20, 59, 59, tzinfo=UTC),
            "21M",
            invites_per_point=2,
            min_stay_hours=168,
            max_points=20,
            num_winners=5,
        )
        self.db.upsert_user(1, "ref", "Ref", now=self.now)
        for uid in range(100, 120):
            self.db.upsert_user(uid, f"u{uid}", f"U{uid}", now=self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_activation_locks_scoring_rules(self):
        self.db.configure_campaign("paeez1405", 3, 72, 10, 5)
        campaign = self.db.activate_campaign("paeez1405", self.now)
        self.assertIsNotNone(campaign.rules_locked_at)
        with self.assertRaises(ValueError):
            self.db.configure_campaign("paeez1405", 2, 168, 20, 5)

    def test_draw_time_is_persisted_and_final_cutoff_is_fixed(self):
        campaign = self.db.get_campaign("paeez1405")
        self.assertEqual(campaign.draw_dt.hour, 18)  # 21:00 Istanbul == 18:00 UTC
        self.assertEqual(
            campaign.final_qualification_cutoff,
            campaign.draw_dt - timedelta(hours=168),
        )

    def test_atomic_pending_finalization_is_idempotent(self):
        campaign = self.db.activate_campaign("paeez1405", self.now)
        self.db.create_pending_referral(campaign, 100, 1, "u100", "U100", self.now)
        first = self.db.finalize_pending_join(campaign, 100, "u100", "U100", self.now)
        second = self.db.finalize_pending_join(campaign, 100, "u100", "U100", self.now)
        self.assertEqual(first, ("created", 1))
        self.assertEqual(second, ("already_recorded", 1))
        self.assertEqual(self.db.campaign_counts(campaign, 1, self.now)["total"], 1)

    def test_pending_reconciliation_includes_already_reminded(self):
        campaign = self.db.activate_campaign("paeez1405", self.now)
        self.db.create_pending_referral(campaign, 101, 1, "u101", "U101", self.now)
        self.db.mark_pending_reminder_sent(campaign.id, 101, self.now)
        self.assertEqual(self.db.pending_reminder_candidates(campaign.id, self.now), [])
        rows = self.db.pending_reconciliation_candidates(campaign.id)
        self.assertEqual([row["joined_user_id"] for row in rows], [101])

    def test_frozen_snapshot_cannot_be_replaced_with_different_entrants(self):
        campaign = self.db.activate_campaign("paeez1405", self.now)
        digest = self.db.save_draw_snapshot(campaign, [(1, 2), (2, 1)], "ok", self.now)
        self.assertEqual(len(digest), 64)
        snap = self.db.draw_snapshot(campaign.id)
        self.assertEqual(json.loads(snap["entrants_json"]), [[1, 2], [2, 1]])
        with self.assertRaises(ValueError):
            self.db.save_draw_snapshot(campaign, [(1, 3)], "changed", self.now)

    def test_reserves_and_seed_source_are_persisted(self):
        campaign = self.db.activate_campaign("paeez1405", self.now)
        entrants = [(uid, 1) for uid in range(100, 107)]
        self.db.save_draw(
            campaign,
            "a" * 64,
            entrants,
            [100, 101, 102, 103, 104],
            "ok",
            self.now,
            reserves=[105, 106],
            seed_source="bitcoin:first-block-after-snapshot:height=1",
        )
        row = self.db.draw_for_campaign(campaign.id)
        self.assertEqual(json.loads(row["reserves_json"]), [105, 106])
        self.assertTrue(row["seed_source"].startswith("bitcoin:"))


if __name__ == "__main__":
    unittest.main()
