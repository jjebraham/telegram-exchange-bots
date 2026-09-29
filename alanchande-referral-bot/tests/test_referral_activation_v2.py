import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from referral_core import ReferralDB
from telegram_bot.growth import source_performance
from telegram_bot.ui import referral_activation_keyboard

UTC = timezone.utc


class ReferralActivationV2Tests(unittest.TestCase):
    def test_referral_keyboard_uses_one_friend_goal_and_gift_framing(self):
        campaign = SimpleNamespace(
            slug="paeez1405",
            name="پاییز ۱۴۰۵",
            num_winners=5,
        )
        link = "https://t.me/Alanchandebot?start=ref_6_example"
        keyboard = referral_activation_keyboard(SimpleNamespace(), link, campaign)

        primary = keyboard.inline_keyboard[0][0]
        self.assertEqual(primary.text, "📤 همین الان برای ۱ نفر")

        query = parse_qs(urlparse(primary.url).query)
        self.assertEqual(query["url"][0], link)
        self.assertIn("۲۱ میلیون تومانی", query["text"][0])
        self.assertIn("اگر دوست داشتی شرکت کنی", query["text"][0])
        self.assertIn("5 برنده", query["text"][0])

    def test_source_report_counts_referral_welcome_instrumentation(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db = ReferralDB(os.path.join(tmp.name, "test.db"))
            db.init()
            now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
            campaign = db.create_campaign(
                "paeez1405",
                "Paeez 1405",
                now - timedelta(days=1),
                now + timedelta(days=30),
                "prizes",
                invites_per_point=2,
                min_stay_hours=168,
                max_points=20,
                num_winners=5,
            )
            db.activate_campaign("paeez1405", now)
            campaign = db.get_campaign("paeez1405")
            db.upsert_user(100, None, "Referral User", now=now)

            db.track_funnel_event(campaign.id, 100, "bot_start", "referral", now)
            db.track_funnel_event(campaign.id, 100, "entered_contest", "referral", now)
            db.track_funnel_event(campaign.id, 100, "referral_welcome_sent", "referral", now)
            db.track_funnel_event(campaign.id, 100, "referral_link_included", "referral", now)
            db.track_funnel_event(campaign.id, 100, "referral_share_prompt_sent", "referral", now)
            db.track_funnel_event(campaign.id, 100, "referral_share_prompt_v2_sent", "referral", now)
            db.save_invite_link(campaign.id, 100, "ref_6_100", now)

            report = source_performance(db, campaign)
            row = next(item for item in report["rows"] if item["source"] == "referral")

            self.assertEqual(row["referral_welcome_sent"], 1)
            self.assertEqual(row["referral_link_included"], 1)
            self.assertEqual(row["referral_share_prompt_sent"], 1)
            self.assertEqual(row["referral_share_prompt_v2_sent"], 1)
            self.assertEqual(row["referral_welcome_error"], 0)
            self.assertEqual(row["referral_link_creation_error"], 0)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
