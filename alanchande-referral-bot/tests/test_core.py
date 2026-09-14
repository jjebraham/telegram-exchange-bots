import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import (
    ReferralDB,
    entrant_snapshot,
    parse_datetime,
    points_from_invites,
    weighted_draw,
)

UTC = timezone.utc


class ReferralCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        self.campaign = self.db.create_campaign(
            "autumn26",
            "Autumn Giveaway",
            self.now - timedelta(days=1),
            self.now + timedelta(days=30),
            "5 prizes",
            invites_per_point=2,
            min_stay_hours=168,
            max_points=20,
            num_winners=5,
        )
        self.db.activate_campaign("autumn26", self.now)
        self.campaign = self.db.get_campaign("autumn26")
        self.db.upsert_user(10, "alice", "Alice", now=self.now)
        self.db.upsert_user(20, "bob", "Bob", now=self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_datetime_requires_timezone(self):
        self.assertEqual(parse_datetime("2026-09-14T15:00:00+03:00").hour, 12)
        with self.assertRaises(ValueError):
            parse_datetime("2026-09-14T15:00:00")

    def test_points_are_capped(self):
        self.assertEqual(points_from_invites(1, 2, 20), 0)
        self.assertEqual(points_from_invites(2, 2, 20), 1)
        self.assertEqual(points_from_invites(100, 2, 20), 20)
        self.assertEqual(points_from_invites(100, 2, 0), 50)

    def test_unique_link_per_user_per_campaign(self):
        one = self.db.save_invite_link(self.campaign.id, 10, "https://t.me/+one", self.now)
        two = self.db.save_invite_link(self.campaign.id, 10, "https://t.me/+two", self.now)
        self.assertEqual(one, "https://t.me/+one")
        self.assertEqual(two, "https://t.me/+one")

    def test_replace_legacy_link_with_deep_link_payload(self):
        self.db.save_invite_link(self.campaign.id, 10, "https://t.me/+legacy", self.now)
        value = self.db.replace_invite_link(self.campaign.id, 10, "ref_1_randomtoken", self.now)
        self.assertEqual(value, "ref_1_randomtoken")
        self.assertEqual(self.db.get_invite_link(self.campaign.id, 10), "ref_1_randomtoken")
        owner = self.db.invite_owner("ref_1_randomtoken")
        self.assertIsNotNone(owner)
        self.assertEqual(owner[1], 10)

    def test_pending_referral_keeps_first_referrer_until_join(self):
        self.db.upsert_user(99, "candidate", "Candidate", now=self.now)
        result, referrer = self.db.create_pending_referral(
            self.campaign, 99, 10, "candidate", "Candidate", self.now
        )
        self.assertEqual((result, referrer), ("created", 10))
        self.assertEqual(self.db.pending_referrer(self.campaign.id, 99), 10)

        result, referrer = self.db.create_pending_referral(
            self.campaign, 99, 20, "candidate", "Candidate", self.now
        )
        self.assertEqual((result, referrer), ("existing", 10))
        self.assertEqual(self.db.pop_pending_referrer(self.campaign.id, 99), 10)
        self.assertIsNone(self.db.pop_pending_referrer(self.campaign.id, 99))

        result = self.db.record_join(self.campaign, 99, 10, "candidate", "Candidate", self.now)
        self.assertEqual(result, "created")
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["pending"], 1)

    def test_first_referrer_is_permanent_and_rejoin_restarts_stay(self):
        first_join = self.now - timedelta(days=10)
        result = self.db.record_join(
            self.campaign, 99, 10, "joined", "Joined", first_join
        )
        self.assertEqual(result, "created")
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["qualified"], 1)

        self.db.mark_left(99, self.now - timedelta(days=1))
        result = self.db.record_join(self.campaign, 99, 20, "joined", "Joined", self.now)
        self.assertEqual(result, "reactivated")
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["pending"], 1)
        self.assertEqual(self.db.campaign_counts(self.campaign, 20, self.now)["total"], 0)

    def test_leave_removes_credit(self):
        self.db.record_join(
            self.campaign, 101, 10, "u101", "U101", self.now - timedelta(days=8)
        )
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["qualified"], 1)
        self.db.mark_left(101, self.now)
        counts = self.db.campaign_counts(self.campaign, 10, self.now)
        self.assertEqual(counts["qualified"], 0)
        self.assertEqual(counts["left"], 1)

    def test_campaigns_do_not_mix(self):
        second = self.db.create_campaign(
            "winter26", "Winter", self.now, self.now + timedelta(days=60), "prize",
            min_stay_hours=168,
        )
        self.db.record_join(
            self.campaign, 200, 10, "u200", "U200", self.now - timedelta(days=8)
        )
        self.db.record_join(
            second, 201, 10, "u201", "U201", self.now - timedelta(days=8)
        )
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["total"], 1)
        self.assertEqual(self.db.campaign_counts(second, 10, self.now)["total"], 1)

    def test_referral_status_list(self):
        self.db.record_join(
            self.campaign, 301, 10, "old", "Old", self.now - timedelta(days=8)
        )
        self.db.record_join(
            self.campaign, 302, 10, "new", "New", self.now - timedelta(days=2)
        )
        self.db.record_join(
            self.campaign, 303, 10, "left", "Left", self.now - timedelta(days=9)
        )
        self.db.mark_left(303, self.now - timedelta(days=1))
        statuses = {row["user_id"]: row["status"] for row in self.db.referral_list(self.campaign, 10, now=self.now)}
        self.assertEqual(statuses[301], "qualified")
        self.assertEqual(statuses[302], "pending")
        self.assertEqual(statuses[303], "left")

    def test_leaderboard_hides_zero_point_users(self):
        self.db.record_join(self.campaign, 401, 10, None, "One", self.now - timedelta(days=8))
        self.db.record_join(self.campaign, 402, 20, None, "Two", self.now - timedelta(days=8))
        self.db.record_join(self.campaign, 403, 20, None, "Three", self.now - timedelta(days=8))
        top = self.db.leaderboard(self.campaign, now=self.now)
        self.assertEqual([r["user_id"] for r in top], [20])
        self.assertEqual(top[0]["points"], 1)

    def test_weighted_draw_is_deterministic_and_unique(self):
        entrants = [(1, 1), (2, 3), (3, 10), (4, 2), (5, 4), (6, 1)]
        first = weighted_draw(entrants, "public-seed", 5)
        second = weighted_draw(list(reversed(entrants)), "public-seed", 5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertEqual(len(set(first)), 5)

    def test_draw_snapshot_and_single_draw(self):
        entrants = [(10, 2), (20, 1)]
        payload, digest = entrant_snapshot(entrants)
        self.assertEqual(json.loads(payload), [[10, 2], [20, 1]])
        self.assertEqual(len(digest), 64)
        winners = weighted_draw(entrants, "seed", 2)
        saved = self.db.save_draw(self.campaign, "seed", entrants, winners, "ok", self.now)
        self.assertEqual(saved, digest)
        with self.assertRaises(ValueError):
            self.db.save_draw(self.campaign, "seed2", entrants, winners, "ok", self.now)
        self.assertEqual(self.db.get_campaign("autumn26").status, "drawn")

    def test_deactivate_referrals_updates_scoring(self):
        for uid in (501, 502):
            self.db.record_join(
                self.campaign, uid, 10, None, f"U{uid}", self.now - timedelta(days=8)
            )
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["points"], 1)
        self.db.deactivate_referrals(self.campaign.id, [501], self.now)
        self.assertEqual(self.db.campaign_counts(self.campaign, 10, self.now)["points"], 0)


if __name__ == "__main__":
    unittest.main()
