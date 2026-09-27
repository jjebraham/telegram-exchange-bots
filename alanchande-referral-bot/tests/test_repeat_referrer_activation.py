import unittest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.ui import main_keyboard, render_home, render_top
from telegram_bot.user_handlers import qualification_pass
from referral_core import ReferralDB


UTC = timezone.utc


def make_campaign():
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=6,
        slug="paeez1405",
        name="پاییز ۱۴۰۵",
        invites_per_point=2,
        min_stay_hours=168,
        max_points=20,
        num_winners=5,
        final_qualification_cutoff=now + timedelta(days=20),
    )


class RepeatReferrerHomeTests(unittest.TestCase):
    def test_home_explains_next_ticket_and_invite_two_cta(self):
        active_campaign = make_campaign()
        counts = {
            "active": 2,
            "current_points": 1,
            "confirmed_points": 1,
            "qualified": 2,
            "pending": 0,
            "qualifiable_pending": 0,
            "left": 0,
        }
        db = SimpleNamespace(
            campaign_counts=lambda _campaign, _user_id: counts,
            pending_referral_count=lambda _campaign_id, _user_id: 0,
            closest_pending_seconds=lambda _campaign, _user_id: None,
        )

        text = render_home(active_campaign, db, 42, "Amir")
        keyboard = main_keyboard(
            SimpleNamespace(channel_url="https://t.me/channel"), active_campaign, counts
        )

        self.assertIn("بلیت تأییدشده: <b>1</b>", text)
        self.assertIn("تا بلیت بعدی", text)
        self.assertIn("۲ دعوت فعال دیگر", text)
        self.assertIn("قرعه‌کشی وزن‌دار", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")

    def test_eligible_pending_referrals_count_toward_the_next_ticket(self):
        from telegram_bot.ui import next_ticket_progress

        active_campaign = make_campaign()
        counts = {
            "active": 4,
            "current_points": 2,
            "confirmed_points": 1,
            "qualified": 2,
            "pending": 2,
            "qualifiable_pending": 2,
        }
        progress, action = next_ticket_progress(active_campaign, counts)
        keyboard = main_keyboard(
            SimpleNamespace(channel_url="https://t.me/channel"), active_campaign, counts
        )

        self.assertIn("برای <b>۱ بلیت دیگر</b> کافی‌اند", progress)
        self.assertIn("پس از دعوت‌های در انتظار", action)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")


class FakeQualificationDB:
    def __init__(self, active_campaign):
        self.campaign = active_campaign
        self.rows = [
            {"id": 1, "referrer_id": 42, "joined_user_id": 100, "joined_first_name": "One"},
            {"id": 2, "referrer_id": 42, "joined_user_id": 101, "joined_first_name": "Two"},
        ]
        self.notified = set()
        self.events = set()

    def live_campaign(self):
        return self.campaign

    def unnotified_qualified(self, _campaign, limit=100):
        return [row for row in self.rows if row["id"] not in self.notified][:limit]

    def campaign_counts(self, _campaign, _referrer_id):
        return {
            "qualified": 2,
            "confirmed_points": 1,
            "current_points": 1,
            "active": 2,
            "pending": 0,
            "qualifiable_pending": 0,
        }

    def qualified_notification_count(self, _campaign, _referrer_id):
        return len(self.notified)

    def has_funnel_event(self, campaign_id, user_id, event_type, _source=""):
        return (campaign_id, user_id, event_type) in self.events

    def mark_qualification_notified(self, referral_id):
        self.notified.add(referral_id)

    def track_funnel_event(self, campaign_id, user_id, event_type, _source=""):
        self.events.add((campaign_id, user_id, event_type))


class FirstTicketNudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_ticket_nudge_is_targeted_once_and_funnel_tracked(self):
        db = FakeQualificationDB(make_campaign())
        bot = SimpleNamespace(send_message=AsyncMock())
        application = SimpleNamespace(bot_data={"db": db}, bot=bot)

        await qualification_pass(application)
        await qualification_pass(application)

        nudge_calls = [
            call for call in bot.send_message.await_args_list
            if "اولین بلیت تأییدشده‌ات ثبت شد" in call.args[1]
        ]
        self.assertEqual(len(nudge_calls), 1)
        self.assertIn("۲ دعوت فعال دیگر", nudge_calls[0].args[1])
        button = nudge_calls[0].kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "menu:link")
        self.assertEqual(button.text, "📤 دعوت ۲ دوست دیگر")
        self.assertIn((6, 42, "first_ticket_nudge_sent"), db.events)


class LeaderboardCopyTests(unittest.TestCase):
    def test_leaderboard_distinguishes_top_ten_from_campaign_participants(self):
        active_campaign = make_campaign()
        db = SimpleNamespace(
            leaderboard=lambda _campaign, limit=10: [
                {
                    "user_id": 42,
                    "first_name": "Amir",
                    "username": None,
                    "current_points": 1,
                    "confirmed_points": 1,
                }
            ],
            leaderboard_position=lambda _campaign, _user_id: (1, 9),
            participant_count=lambda _campaign_id: 27,
        )

        text = render_top(active_campaign, db, user_id=42)

        self.assertIn("فقط ۱۰ کاربر امتیازدار اول", text)
        self.assertIn("شرکت‌کنندگان دارای لینک اختصاصی: <b>27</b>", text)
        self.assertIn("قرعه‌کشی وزن‌دار", text)
        self.assertIn("درصد ثابت یا برد تضمینی", text)


class ReferralProgressStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
        campaign = self.db.create_campaign(
            "repeat_test",
            "Repeat Test",
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
        self.db.upsert_user(42, "referrer", "Referrer", now=self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_campaign_counts_only_include_by_draw_pending_in_next_ticket_path(self):
        self.db.record_join(
            self.campaign, 100, 42, "eligible", "Eligible", self.now
        )
        self.db.record_join(
            self.campaign,
            101,
            42,
            "late",
            "Late",
            self.campaign.final_qualification_cutoff + timedelta(hours=1),
        )

        counts = self.db.campaign_counts(self.campaign, 42, self.now)

        self.assertEqual(counts["pending"], 2)
        self.assertEqual(counts["qualifiable_pending"], 1)

    def test_first_ticket_funnel_event_and_notification_count_are_queryable(self):
        joined_at = self.now - timedelta(days=8)
        self.db.record_join(
            self.campaign, 100, 42, "joined", "Joined", joined_at
        )
        row = self.db.unnotified_qualified(self.campaign, now=self.now)[0]
        self.db.mark_qualification_notified(row["id"], self.now)
        self.db.track_funnel_event(
            self.campaign.id, 42, "first_ticket_nudge_sent", "", self.now
        )

        self.assertEqual(self.db.qualified_notification_count(self.campaign, 42, self.now), 1)
        self.assertTrue(self.db.has_funnel_event(
            self.campaign.id, 42, "first_ticket_nudge_sent", ""
        ))
        self.assertFalse(self.db.has_funnel_event(
            self.campaign.id, 42, "first_ticket_nudge_sent", "other"
        ))


if __name__ == "__main__":
    unittest.main()
