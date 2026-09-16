from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from telegram_bot.config import Settings
from telegram_bot.growth import qualification_cutoff_text
from telegram_bot.promo_handlers import _entry_text
from telegram_bot.ui import final_join_cutoff_text, link_keyboard


class GrowthActivationTests(unittest.TestCase):
    def _campaign(self):
        cutoff = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
        return SimpleNamespace(
            name="پاییز ۱۴۰۵",
            prize_text="۲۱ میلیون تومان",
            invites_per_point=2,
            num_winners=5,
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

    def test_cutoff_is_rendered_in_both_timezones(self):
        campaign = self._campaign()
        ui_text = final_join_cutoff_text(campaign)
        growth_text = qualification_cutoff_text(campaign)
        self.assertIn("2026/10/09", ui_text)
        self.assertIn("21:00", ui_text)
        self.assertIn("21:30", ui_text)
        self.assertIn("21:00", growth_text)
        self.assertIn("21:30", growth_text)

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
