import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from telegram_bot.ui import render_top


class LeaderboardLayoutTests(unittest.TestCase):
    def test_mixed_names_and_rank_seven_have_consistent_rtl_paragraphs(self):
        names = ["Mary", "Neda", "👦Ali", "iM", "HK", "عظیم", "Ray", "Other", "Nine", "Ten"]
        rows = [dict(first_name=name, username=None, user_id=i,
                     current_points=2 if i < 2 else 1, confirmed_points=i % 2)
                for i, name in enumerate(names)]
        db = Mock()
        db.leaderboard.return_value = rows
        db.leaderboard_position.return_value = (7, 12)
        db.participant_count.return_value = 132
        campaign = SimpleNamespace(id=1, name="پاییز ۱۴۰۵")
        text = render_top(campaign, db, 6)
        self.assertTrue(all(line.startswith("\u200f") for line in text.splitlines() if line))
        self.assertIn("\u200f۷) \u2068<b>Ra***</b>\u2069", text)
        self.assertIn("\u200f۶) \u2068<b>عظ***</b>\u2069", text)
        self.assertIn("\u200f۱۰)", text)
        self.assertIn("رتبه تو بین کاربران امتیازدار: <b>۷</b> از <b>۱۲</b>", text)
        self.assertIn("کل شرکت‌کنندگان دارای لینک اختصاصی: <b>۱۳۲</b>", text)
        self.assertIn("فقط ۱۰ کاربر امتیازدار", text)
        self.assertIn("قرعه‌کشی وزن‌دار", text)
        self.assertIn("شانس برنده‌شدن افزایش می‌دهد", text)
        self.assertNotIn("%", text)
        self.assertIn("امتیاز موقت: <b>۲</b>", text)
        self.assertIn("بلیت تأییدشده: <b>۰</b>", text)
        self.assertEqual(text.count("\u2068"), 10)
        self.assertEqual(text.count("\u2069"), 10)
        self.assertLess(text.index("Ma***"), text.index("Ne***"))
        db.leaderboard.assert_called_once_with(campaign, limit=10)
        db.leaderboard_position.assert_called_once_with(campaign, 6)

    def test_user_directional_controls_cannot_break_isolation_or_masking(self):
        db = Mock()
        db.participant_count.return_value = 1
        db.leaderboard.return_value = [dict(first_name="\u202e\u2069\u200fA<B",
            username=None, user_id=12, current_points=1, confirmed_points=0)]
        text = render_top(SimpleNamespace(id=1, name="<Campaign>"), db)
        self.assertIn("&lt;Campaign&gt;", text)
        self.assertIn("\u2068<b>A&lt;***</b>\u2069", text)
        self.assertNotIn("\u202e", text)
        self.assertEqual(text.count("\u2069"), 1)
        db.leaderboard_position.assert_not_called()

    def test_empty_leaderboard_retains_rtl_empty_state(self):
        db = Mock()
        db.participant_count.return_value = 0
        db.leaderboard.return_value = []
        text = render_top(SimpleNamespace(id=1, name="Campaign"), db)
        self.assertIn("هنوز امتیازی", text)
        self.assertIn("کل شرکت‌کنندگان دارای لینک اختصاصی: <b>۰</b>", text)
        self.assertTrue(all(line.startswith("\u200f") for line in text.splitlines() if line))
