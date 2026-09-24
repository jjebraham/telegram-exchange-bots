import unittest
from types import SimpleNamespace

from telegram_bot.user_handlers import referral_join_progress_message


class ReferralProgressMessageTests(unittest.TestCase):
    def campaign(self):
        return SimpleNamespace(
            invites_per_point=2,
            min_stay_hours=168,
        )

    def test_first_active_referral_shows_one_of_two_and_one_more_cta(self):
        text, button, one_more = referral_join_progress_message(
            self.campaign(),
            {"active": 1, "current_points": 0},
            "created",
        )

        self.assertTrue(one_more)
        self.assertEqual(button, "📤 فقط ۱ نفر دیگه")
        self.assertIn("اولین دعوتت ثبت شد", text)
        self.assertIn("۱/۲", text)
        self.assertIn("فقط <b>۱ نفر دیگه</b>", text)

    def test_odd_active_count_after_first_point_targets_next_point(self):
        text, button, one_more = referral_join_progress_message(
            self.campaign(),
            {"active": 3, "current_points": 1},
            "created",
        )

        self.assertTrue(one_more)
        self.assertEqual(button, "📤 فقط ۱ نفر دیگه")
        self.assertIn("پیشرفت امتیاز بعدی", text)
        self.assertIn("۱/۲", text)
        self.assertNotIn("اولین دعوتت ثبت شد", text)

    def test_completed_pair_keeps_normal_next_referral_message(self):
        text, button, one_more = referral_join_progress_message(
            self.campaign(),
            {"active": 2, "current_points": 1},
            "created",
        )

        self.assertFalse(one_more)
        self.assertEqual(button, "📤 دعوت نفر بعدی")
        self.assertIn("امتیاز موقتت الان: <b>1</b>", text)
        self.assertIn("تا امتیاز موقت بعدی: <b>2</b>", text)


if __name__ == "__main__":
    unittest.main()
