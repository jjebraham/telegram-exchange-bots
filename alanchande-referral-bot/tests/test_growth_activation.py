from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from referral_core import ReferralDB
from telegram_bot.config import Settings
from telegram_bot.growth import qualification_cutoff_text
from telegram_bot.promo_handlers import _entry_text
from telegram_bot.reminders import _qualification_soon_candidates
from telegram_bot.ui import final_join_cutoff_text, link_keyboard, render_home


class GrowthActivationTests(unittest.TestCase):
    def _campaign(self):
        cutoff = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
        return SimpleNamespace(
            name="پاییز ۱۴۰۵",
            prize_text="۲۱ میلیون تومان",
            invites_per_point=2,
            num_winners=5,
            max_points=20,
            min_stay_hours=168,
            final_qualification_cutoff=cutoff,
        )

    def test_member_variant_b_is_short_and_action_focused(self):
        text = _entry_text(self._campaign(), True, "b")
        self.assertIn("عضو کانال هستی", text)
        self.assertIn("۲۱ میلیون تومان", text)
        self.assertIn("هر <b>2 دعوت فعال</b>", text)
        self.assertNotIn("پایان ثبت دعوت", text)

    def test_share_keyboard_has_clear_primary_cta(self):
        keyboard = link_keyboard(None, "https://t.me/testbot?start=ref_1_x", self._campaign())
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 ارسال لینک برای دوستان")
        self.assertTrue(keyboard.inline_keyboard[0][0].url.startswith("https://t.me/share/url?"))

    def test_home_card_makes_first_and_next_referral_progress_visible(self):
        class FakeDB:
            def __init__(self, active):
                self.active = active

            def campaign_counts(self, campaign, user_id):
                return {
                    "active": self.active,
                    "current_points": self.active // campaign.invites_per_point,
                    "confirmed_points": 0,
                    "pending": self.active,
                }

            def pending_referral_count(self, campaign_id, user_id):
                return 0

            def closest_pending_seconds(self, campaign, user_id):
                return None

        campaign = self._campaign()

        first = render_home(campaign, FakeDB(0), 10, "Ali")
        self.assertIn("0/2", first)
        self.assertIn("برای چند نفر بفرست", first)
        self.assertIn("دعوت فعال: <b>0</b>", first)

        halfway = render_home(campaign, FakeDB(1), 10, "Ali")
        self.assertIn("1/2", halfway)
        self.assertIn("فقط <b>۱ دعوت فعال</b>", halfway)

    def test_cutoff_is_rendered_in_both_timezones(self):
        campaign = self._campaign()
        ui_text = final_join_cutoff_text(campaign)
        growth_text = qualification_cutoff_text(campaign)
        self.assertIn("2026/10/09", ui_text)
        self.assertIn("21:00", ui_text)
        self.assertIn("21:30", ui_text)
        self.assertIn("21:00", growth_text)
        self.assertIn("21:30", growth_text)

    def test_qualification_soon_nudge_is_once_per_referral(self):
        now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            db = ReferralDB(os.path.join(tmp, "engagement.sqlite"))
            db.init()
            campaign = db.create_campaign(
                "engage",
                "Engagement",
                now - timedelta(days=10),
                now + timedelta(days=30),
                "prizes",
                invites_per_point=2,
                min_stay_hours=168,
                max_points=20,
                num_winners=5,
            )
            db.activate_campaign(campaign.slug, now)
            campaign = db.get_campaign(campaign.slug)
            db.upsert_user(10, "referrer", "Referrer", now=now)

            db.record_join(
                campaign, 101, 10, "u101", "U101", now - timedelta(hours=167)
            )
            db.record_join(
                campaign, 102, 10, "u102", "U102", now - timedelta(hours=100)
            )

            rows = _qualification_soon_candidates(
                db, campaign, now, within_hours=24, limit=100
            )
            self.assertEqual([row["joined_user_id"] for row in rows], [101])

            db.track_funnel_event(
                campaign.id,
                10,
                "nudge_qualification_soon_sent",
                "referral:101",
                now,
            )
            rows = _qualification_soon_candidates(
                db, campaign, now, within_hours=24, limit=100
            )
            self.assertEqual(rows, [])

    def test_early_share_nudge_defaults_to_two_hours(self):
        env = {
            "BOT_TOKEN": "123:test",
            "CHANNEL_ID": "-1001234567890",
            "ADMIN_IDS": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.early_share_nudge_hours, 2)


if __name__ == "__main__":
    unittest.main()
