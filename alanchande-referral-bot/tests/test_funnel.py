import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from referral_core import ReferralDB
from telegram_bot.admin_handlers import _extended_funnel, _review_signals
from telegram_bot.growth import (
    build_promo_link,
    normalize_promo_source,
    promo_variant,
    remaining_text,
    source_performance,
)

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

    def test_daily_metrics_are_upserted_per_istanbul_day(self):
        self.db.track_funnel_event(self.campaign.id, 20, "bot_start", "bigchannel", self.now)
        self.db.save_invite_link(self.campaign.id, 20, "ref_1_bob", self.now)
        self.db.record_join(self.campaign, 30, 20, None, "Carol", self.now)

        first = self.db.capture_daily_metrics(self.campaign, self.now)
        self.assertEqual(first["snapshot_date"], "2026-09-15")
        self.assertEqual(first["participants"], 1)
        self.assertEqual(first["joined"], 1)

        self.db.upsert_user(50, None, "Eve", now=self.now)
        self.db.record_join(self.campaign, 50, 20, None, "Eve", self.now)
        second = self.db.capture_daily_metrics(self.campaign, self.now + timedelta(hours=1))
        self.assertEqual(second["joined"], 2)
        rows = self.db.daily_metrics(self.campaign.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["joined"], 2)

    def test_zero_referral_and_promo_abandon_nudge_candidates(self):
        link_at = self.now - timedelta(hours=20)
        self.db.save_invite_link(self.campaign.id, 20, "ref_1_bob", link_at)
        zero = self.db.zero_referral_nudge_candidates(
            self.campaign.id, self.now - timedelta(hours=12)
        )
        self.assertEqual([row["user_id"] for row in zero], [20])
        self.db.track_funnel_event(
            self.campaign.id, 20, "nudge_zero_referral_sent", "", self.now
        )
        self.assertEqual(
            self.db.zero_referral_nudge_candidates(
                self.campaign.id, self.now - timedelta(hours=12)
            ),
            [],
        )

        start_at = self.now - timedelta(hours=5)
        self.db.track_funnel_event(self.campaign.id, 30, "bot_start", "instagram", start_at)
        promo = self.db.promo_abandon_nudge_candidates(
            self.campaign.id, self.now - timedelta(hours=3)
        )
        self.assertEqual([row["user_id"] for row in promo], [30])
        self.db.save_invite_link(self.campaign.id, 30, "ref_1_carol", self.now)
        self.assertEqual(
            self.db.promo_abandon_nudge_candidates(
                self.campaign.id, self.now - timedelta(hours=3)
            ),
            [],
        )

    def test_notification_throttle_suppresses_and_summarizes_bursts(self):
        self.assertTrue(self.db.notification_gate(self.campaign.id, 20, 2, 600, self.now))
        self.assertTrue(self.db.notification_gate(self.campaign.id, 20, 2, 600, self.now))
        self.assertFalse(self.db.notification_gate(self.campaign.id, 20, 2, 600, self.now))
        due = self.db.notification_summaries_due(
            self.campaign.id, self.now + timedelta(seconds=601)
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["suppressed_count"], 1)
        self.db.clear_notification_summary(self.campaign.id, 20, self.now + timedelta(seconds=602))
        self.assertEqual(
            self.db.notification_summaries_due(
                self.campaign.id, self.now + timedelta(seconds=1200)
            ),
            [],
        )

    def test_promo_helpers_normalize_variant_and_countdown(self):
        self.assertEqual(normalize_promo_source(" Instagram Story!! "), "instagram_story")
        self.assertEqual(
            build_promo_link("Alanchandebot", "mainchannel", "a"),
            "https://t.me/Alanchandebot?start=promo_mainchannel_a",
        )
        self.assertEqual(promo_variant("mainchannel_a"), "a")
        self.assertEqual(promo_variant("mainchannel_b"), "b")
        self.assertEqual(promo_variant("mainchannel"), "default")
        self.assertEqual(remaining_text(30 * 86400 + 2 * 3600), "30 روز و 2 ساعت")
        self.assertEqual(remaining_text(25 * 3600), "1 روز و 1 ساعت")

    def test_source_performance_separates_tracked_and_legacy(self):
        start = self.now - timedelta(hours=3)
        self.db.track_funnel_event(self.campaign.id, 20, "bot_start", "mainchannel_a", start)
        self.db.track_funnel_event(self.campaign.id, 20, "entered_contest", "mainchannel_a", start)
        self.db.save_invite_link(self.campaign.id, 20, "ref_1_bob", start)
        self.db.track_funnel_event(self.campaign.id, 30, "referral_open", "referral", self.now)
        self.db.record_join(self.campaign, 30, 20, None, "Carol", self.now)

        self.db.save_invite_link(self.campaign.id, 10, "ref_1_alice", start)
        self.db.record_join(self.campaign, 40, 10, None, "Dave", self.now)

        report = source_performance(self.db, self.campaign)
        rows = {row["source"]: row for row in report["rows"]}
        self.assertEqual(rows["mainchannel_a"]["starts"], 1)
        self.assertEqual(rows["mainchannel_a"]["entered"], 1)
        self.assertEqual(rows["mainchannel_a"]["links"], 1)
        self.assertEqual(rows["mainchannel_a"]["joins"], 1)
        self.assertEqual(rows["mainchannel_a"]["referral_opens"], 1)
        self.assertEqual(rows["legacy/untracked"]["joins"], 1)


if __name__ == "__main__":
    unittest.main()
