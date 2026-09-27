import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.ui import main_keyboard, next_ticket_progress, render_home
from telegram_bot.user_handlers import qualification_pass


UTC = timezone.utc


def campaign():
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=6,
        slug="paeez1405",
        name="پاییز ۱۴۰۵",
        invites_per_point=2,
        min_stay_hours=168,
        max_points=20,
        final_qualification_cutoff=now + timedelta(days=20),
    )


class RepeatReferrerHomeTests(unittest.TestCase):
    def test_users_without_tickets_keep_temporary_point_progress(self):
        progress, action = next_ticket_progress(
            campaign(),
            {
                "active": 1,
                "current_points": 0,
                "confirmed_points": 0,
                "qualified": 0,
                "qualifiable_pending": 1,
            },
        )

        self.assertIn("تا امتیاز موقت بعدی", progress)
        self.assertIn("۱ دعوت فعال دیگر", action)

    def test_home_shows_next_ticket_path_and_invite_two_cta(self):
        db = SimpleNamespace(
            campaign_counts=lambda _campaign, _user_id: {
                "active": 2,
                "current_points": 1,
                "confirmed_points": 1,
                "qualified": 2,
                "pending": 0,
                "qualifiable_pending": 0,
                "left": 0,
            },
            pending_referral_count=lambda _campaign_id, _user_id: 0,
            closest_pending_seconds=lambda _campaign, _user_id: None,
        )
        active_campaign = campaign()

        text = render_home(active_campaign, db, 42, "Amir")
        keyboard = main_keyboard(
            SimpleNamespace(channel_url="https://t.me/channel"),
            active_campaign,
            db.campaign_counts(active_campaign, 42),
        )

        self.assertIn("بلیت تأییدشده: <b>1</b>", text)
        self.assertIn("تا بلیت بعدی", text)
        self.assertIn("۲ دعوت فعال دیگر", text)
        self.assertIn("قرعه‌کشی وزن‌دار", text)
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

    def has_funnel_event(self, _campaign_id, user_id, event_type, _source=""):
        return (_campaign_id, user_id, event_type) in self.events

    def mark_qualification_notified(self, referral_id):
        self.notified.add(referral_id)

    def track_funnel_event(self, campaign_id, user_id, event_type, _source=""):
        self.events.add((campaign_id, user_id, event_type))


class FirstTicketNudgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_confirmed_ticket_gets_one_targeted_nudge(self):
        db = FakeQualificationDB(campaign())
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

    def test_existing_eligible_pending_referrals_are_counted_before_new_cta(self):
        active_campaign = campaign()
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
            SimpleNamespace(channel_url="https://t.me/channel"),
            active_campaign,
            counts,
        )

        self.assertIn("برای <b>۱ بلیت دیگر</b> کافی‌اند", progress)
        self.assertIn("پس از دعوت‌های در انتظار", action)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")


if __name__ == "__main__":
    unittest.main()
