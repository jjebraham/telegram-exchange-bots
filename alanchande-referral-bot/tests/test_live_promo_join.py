import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, Update, User
from telegram.error import Forbidden
from telegram.ext import ChatMemberHandler
from telegram_bot.app import create_application
from telegram_bot.config import Settings
from telegram_bot.growth import source_performance


class RegisteredPromoJoinTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(bot_token="123456:TEST_TOKEN", channel_id_raw="-100123",
            channel_url="https://t.me/alanchande_com", admin_ids=frozenset(),
            db_path=os.path.join(self.tmp.name, "test.db"))
        self.app = create_application(settings)
        self.db = self.app.bot_data["db"]
        self.now = datetime.now(timezone.utc)
        c = self.db.create_campaign("live", "Live", self.now - timedelta(days=1),
            self.now + timedelta(days=20), "Prizes", invites_per_point=2,
            min_stay_hours=168, max_points=20, num_winners=5)
        self.db.activate_campaign(c.slug, self.now)
        self.campaign = self.db.get_campaign(c.slug)
        self.user = User(100, "Entrant", False, username="entrant")
        self.context = SimpleNamespace(application=self.app,
            bot=SimpleNamespace(username="Alanchandebot", send_message=AsyncMock()))
        self.handler = next(h for handlers in self.app.handlers.values() for h in handlers
                            if isinstance(h, ChatMemberHandler))

    def tearDown(self):
        self.tmp.cleanup()

    def waiting(self):
        self.db.upsert_user(self.user.id, self.user.username, self.user.first_name)
        for event in ("bot_start", "entry_needs_membership"):
            self.db.track_funnel_event(self.campaign.id, self.user.id, event, "meditation_b", self.now)

    async def join(self, channel_id=-100123):
        update = Update(1, chat_member=ChatMemberUpdated(
            Chat(channel_id, "channel"), self.user, self.now,
            ChatMemberLeft(self.user), ChatMemberMember(self.user)))
        self.assertTrue(self.handler.check_update(update))
        await self.handler.callback(update, self.context)

    async def test_registered_handler_completes_promo_join_once(self):
        self.waiting()
        await self.join()
        link = self.db.get_invite_link(self.campaign.id, self.user.id)
        self.assertTrue(link and link.startswith("ref_"))
        self.context.bot.send_message.assert_awaited_once()
        await self.join()
        self.assertEqual(self.db.get_invite_link(self.campaign.id, self.user.id), link)
        self.context.bot.send_message.assert_awaited_once()
        row = next(r for r in source_performance(self.db, self.campaign)["rows"]
                   if r["source"] == "meditation_b")
        self.assertEqual((row["entered"], row["entry_auto_join_completed"],
                          row["entry_auto_join_message_sent"]), (1, 1, 1))

    async def test_unrelated_and_wrong_channel_joins_do_not_enroll(self):
        await self.join()
        self.assertIsNone(self.db.get_invite_link(self.campaign.id, self.user.id))
        self.waiting()
        await self.join(channel_id=-100999)
        self.assertIsNone(self.db.get_invite_link(self.campaign.id, self.user.id))
        self.context.bot.send_message.assert_not_awaited()

    async def test_pending_referral_keeps_priority_over_old_promo_intent(self):
        self.waiting()
        self.db.upsert_user(200, None, "Referrer")
        self.db.create_pending_referral(self.campaign, self.user.id, 200, "entrant", "Entrant")
        with patch("telegram_bot.referral_success.send_participant_welcome", new_callable=AsyncMock) as welcome, \
             patch("telegram_bot.live_runtime.notify_referral_join", new_callable=AsyncMock), \
             patch("telegram_bot.promo_handlers.auto_complete_promo_join", new_callable=AsyncMock) as auto:
            await self.join()
            welcome.assert_awaited_once()
            auto.assert_not_awaited()
        self.assertEqual(self.db.referrer_for_joined(self.campaign.id, self.user.id), 200)

    async def test_original_referral_rejoin_keeps_priority(self):
        self.waiting()
        self.db.upsert_user(200, None, "Referrer")
        self.db.record_join(self.campaign, self.user.id, 200, "entrant", "Entrant")
        self.db.mark_left(self.user.id)
        with patch("telegram_bot.referral_success.send_participant_welcome", new_callable=AsyncMock) as welcome, \
             patch("telegram_bot.live_runtime.notify_referral_join", new_callable=AsyncMock), \
             patch("telegram_bot.promo_handlers.auto_complete_promo_join", new_callable=AsyncMock) as auto:
            await self.join()
            welcome.assert_awaited_once()
            auto.assert_not_awaited()
        self.assertEqual(self.db.referrer_for_joined(self.campaign.id, self.user.id), 200)

    async def test_delivery_failure_keeps_entry_and_reports_error(self):
        self.waiting()
        self.context.bot.send_message.side_effect = Forbidden("blocked")
        await self.join()
        self.assertIsNotNone(self.db.get_invite_link(self.campaign.id, self.user.id))
        row = next(r for r in source_performance(self.db, self.campaign)["rows"]
                   if r["source"] == "meditation_b")
        self.assertEqual((row["entry_auto_join_completed"], row["entry_auto_join_message_error"]), (1, 1))
