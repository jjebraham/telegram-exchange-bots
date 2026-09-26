import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from referral_core import ReferralDB
from telegram_bot.growth import source_performance
from telegram_bot.promo_handlers import (
    _entry_text,
    auto_complete_promo_join,
)

UTC = timezone.utc


class PromoAutoEntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime(2026, 9, 24, 16, 0, tzinfo=UTC)
        campaign = self.db.create_campaign(
            "paeez1405",
            "پاییز ۱۴۰۵",
            self.now - timedelta(days=10),
            self.now + timedelta(days=21),
            "۲۱ میلیون تومان",
            invites_per_point=2,
            min_stay_hours=168,
            max_points=20,
            num_winners=5,
        )
        self.db.activate_campaign(campaign.slug, self.now)
        self.campaign = self.db.get_campaign(campaign.slug)

        self.bot = SimpleNamespace(
            username="Alanchandebot",
            send_message=AsyncMock(),
        )
        self.settings = SimpleNamespace(
            channel_url="https://t.me/alanchande_com",
        )
        self.context = SimpleNamespace(
            bot=self.bot,
            application=SimpleNamespace(
                bot_data={
                    "settings": self.settings,
                    "db": self.db,
                }
            ),
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_channel_join_auto_completes_waiting_promo_user_once(self):
        user = SimpleNamespace(
            id=100,
            username="promo_user",
            first_name="Promo",
            last_name=None,
        )
        self.db.upsert_user(user.id, user.username, user.first_name, user.last_name, now=self.now)
        self.db.track_funnel_event(
            self.campaign.id,
            user.id,
            "bot_start",
            "mainchannel_b",
            self.now,
        )
        self.db.track_funnel_event(
            self.campaign.id,
            user.id,
            "entry_needs_membership",
            "mainchannel_b",
            self.now,
        )

        completed = await auto_complete_promo_join(
            self.context,
            self.campaign,
            user,
        )

        self.assertTrue(completed)
        self.assertTrue(self.db.get_invite_link(self.campaign.id, user.id))
        self.bot.send_message.assert_awaited_once()

        with self.db.connect() as conn:
            events = {
                row["event_type"]
                for row in conn.execute(
                    """SELECT event_type FROM funnel_events
                       WHERE campaign_id=? AND user_id=?""",
                    (self.campaign.id, user.id),
                ).fetchall()
            }
        self.assertIn("entry_auto_join_completed", events)
        self.assertIn("entry_auto_join_message_sent", events)
        self.assertIn("entered_contest", events)
        self.assertIn("entry_link_created", events)

        # A repeated Telegram membership update must not create/send twice.
        completed_again = await auto_complete_promo_join(
            self.context,
            self.campaign,
            user,
        )
        self.assertFalse(completed_again)
        self.assertEqual(self.bot.send_message.await_count, 1)

        report = source_performance(self.db, self.campaign)
        row = next(item for item in report["rows"] if item["source"] == "mainchannel_b")
        self.assertEqual(row["entry_auto_join_completed"], 1)
        self.assertEqual(row["entry_auto_join_message_sent"], 1)

    async def test_unrelated_channel_join_is_not_auto_enrolled(self):
        user = SimpleNamespace(
            id=200,
            username="unrelated",
            first_name="Unrelated",
            last_name=None,
        )
        self.db.upsert_user(user.id, user.username, user.first_name, user.last_name, now=self.now)

        completed = await auto_complete_promo_join(
            self.context,
            self.campaign,
            user,
        )

        self.assertFalse(completed)
        self.assertIsNone(self.db.get_invite_link(self.campaign.id, user.id))
        self.bot.send_message.assert_not_awaited()

    def test_nonmember_entry_copy_explains_automatic_completion_and_fallback(self):
        text = _entry_text(self.campaign, False, "b")

        self.assertIn("به‌صورت خودکار", text)
        self.assertIn("اگر پیام خودکار نیامد", text)
        self.assertIn("عضو شدم؛ شروع مسابقه", text)


if __name__ == "__main__":
    unittest.main()
