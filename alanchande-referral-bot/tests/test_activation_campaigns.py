import asyncio
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from telegram.constants import ChatType
from telegram.error import Forbidden, RetryAfter, TimedOut

from referral_core import ReferralDB
from telegram_bot.activation_campaigns import (
    activation_keyboard, activation_message, cmd_activation_preview,
    cmd_activation_report, on_activation_callback, send_activation_campaign,
)
from telegram_bot.activation_store import (
    activity_snapshot, activation_report, claim_recipient, eligibility,
    eligible_recipients, finish_recipient, get_run, pending_recipients, start_run,
)


class ActivationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bot.db")
        self.db = ReferralDB(self.path)
        self.db.init()
        self.now = datetime.now(timezone.utc)
        c = self.db.create_campaign("activation", "<Test>", self.now - timedelta(days=12),
                                    self.now + timedelta(days=30), "prizes")
        self.db.activate_campaign(c.slug, self.now - timedelta(days=11))
        self.c = self.db.get_campaign(c.slug)
        self.counter = 1000
        self.settings = SimpleNamespace(admin_ids={999, 998}, notification_max_per_window=5,
                                        notification_window_seconds=600)
        self.bot = SimpleNamespace(username="TestBot", send_message=AsyncMock(
            return_value=SimpleNamespace(message_id=123, date=self.now)))
        self.app = SimpleNamespace(bot_data={"db": self.db, "settings": self.settings}, bot=self.bot)
        self.tasks = []

        def create_task(coro):
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task
        self.app.create_task = create_task
        self.context = SimpleNamespace(application=self.app, bot=self.bot, args=[])
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.update = SimpleNamespace(message=self.message, effective_user=SimpleNamespace(id=999),
            effective_chat=SimpleNamespace(type=ChatType.PRIVATE, id=999), callback_query=None)

    def tearDown(self):
        self.tmp.cleanup()

    def holder(self, uid, source="referral", created=None):
        when = created or self.now - timedelta(days=3)
        self.db.upsert_user(uid, None, "User", now=when)
        self.db.track_funnel_event(self.c.id, uid, "bot_start", source, when)
        self.db.track_funnel_event(self.c.id, uid, "entered_contest", source, when)
        self.db.save_invite_link(self.c.id, uid, f"ref_{self.c.id}_user{uid}", when)

    def join(self, owner, when=None, uid=None):
        self.counter += 1
        uid = uid or self.counter
        self.db.record_join(self.c, uid, owner, None, "Friend", when or self.now - timedelta(days=8))
        return uid

    def one_ticket(self, uid=10, qualified=2, pending=0):
        self.holder(uid, "mainchannel_b")
        for _ in range(qualified):
            self.join(uid)
        for _ in range(pending):
            self.join(uid, self.now - timedelta(days=1))

    def open(self, uid, candidate, when=None, campaign_id=None):
        self.db.track_funnel_event(campaign_id or self.c.id, uid, "referral_open_received",
                                  f"candidate:{candidate}", when or self.now)

    def preview(self, segment="next_ticket", user_ids=None, expires=None, admin=999):
        token = "testtoken"
        self.app.bot_data["activation_previews"] = {token: {
            "campaign_id": self.c.id, "segment": segment, "admin_id": admin,
            "user_ids": user_ids or [10], "expires_at": expires or time.time() + 900,
        }}
        query = SimpleNamespace(data=f"activate:yes:{token}", answer=AsyncMock(),
                                edit_message_reply_markup=AsyncMock())
        self.update.callback_query = query
        return query

    async def run_sender(self, segment="next_ticket", user_ids=None):
        start_run(self.db, self.c, segment, 999, user_ids or [10], self.now)
        with patch("telegram_bot.activation_campaigns.asyncio.sleep", new=AsyncMock()):
            await send_activation_campaign(self.app, self.c.id, segment, "TestBot", 999)

    def recipient_calls(self, uid=10):
        return [c for c in self.bot.send_message.await_args_list if c.args[0] == uid]

    def test_cohorts_are_separate_and_first_touch_is_preserved(self):
        self.one_ticket()
        self.holder(20)
        self.holder(30, "organic")
        self.db.track_funnel_event(self.c.id, 20, "bot_start", "organic", self.now)
        self.db.track_funnel_event(self.c.id, 30, "bot_start", "referral", self.now)
        self.assertEqual([r["user_id"] for r in eligible_recipients(self.db, self.c, "next_ticket", self.now)], [10])
        self.assertEqual([r["user_id"] for r in eligible_recipients(self.db, self.c, "first_friend", self.now)], [20])

    def test_first_friend_excludes_opens_pending_and_historical_inactive_referrals(self):
        for uid in (10, 20, 30, 40):
            self.holder(uid)
        self.open(10, 123)
        self.db.upsert_user(321, None, "Pending")
        self.db.create_pending_referral(self.c, 321, 20, None, "Pending", self.now)
        joined = self.join(30)
        self.db.mark_left(joined, self.now)
        self.assertEqual([r["user_id"] for r in eligible_recipients(self.db, self.c, "first_friend", self.now)], [40])

    def test_recent_contact_and_new_holders_are_excluded_with_exact_boundary(self):
        self.holder(10, created=self.now - timedelta(hours=24))
        self.holder(20, created=self.now - timedelta(hours=24) + timedelta(seconds=1))
        self.db.track_funnel_event(self.c.id, 10, "nudge_early_share_sent", "referral",
                                  self.now - timedelta(hours=24))
        self.assertIsNotNone(eligibility(self.db, self.c, 10, "first_friend", self.now)[0])
        self.assertIsNone(eligibility(self.db, self.c, 20, "first_friend", self.now)[0])
        self.db.track_funnel_event(self.c.id, 10, "first_ticket_nudge_sent", "",
                                  self.now - timedelta(hours=23))
        self.assertEqual(eligibility(self.db, self.c, 10, "first_friend", self.now)[1], "recent_contact")

    def test_cap_deadline_closed_campaign_and_legacy_links_are_respected(self):
        self.one_ticket()
        self.assertEqual(eligibility(self.db, replace(self.c, max_points=1), 10, "next_ticket", self.now)[1], "ticket_cap")
        self.assertEqual(eligibility(self.db, replace(self.c, status="closed"), 10, "next_ticket", self.now)[1], "campaign_not_live")
        deadline = self.c.final_qualification_cutoff
        self.assertIsNone(eligibility(self.db, self.c, 10, "next_ticket", deadline)[0])
        self.db.replace_invite_link(self.c.id, 10, "https://t.me/+legacy")
        self.assertEqual(eligibility(self.db, self.c, 10, "next_ticket", self.now)[1], "no_personal_deep_link")

    def test_copy_accounts_for_qualified_remainder_pending_and_waiting(self):
        self.one_ticket()
        counts = self.db.campaign_counts(self.c, 10, self.now)
        text, label, waiting = activation_message(self.c, counts, "next_ticket")
        self.assertEqual(label, "📤 دعوت ۲ دوست دیگر")
        self.assertIn("&lt;Test&gt;", text)
        self.assertIn("7 روز", text)
        self.assertFalse(waiting)
        self.join(10, self.now - timedelta(days=1))
        counts = self.db.campaign_counts(self.c, 10, self.now)
        self.assertEqual(activation_message(self.c, counts, "next_ticket")[1], "📤 دعوت ۱ دوست دیگر")
        self.join(10, self.now - timedelta(days=1))
        text, label, waiting = activation_message(self.c, self.db.campaign_counts(self.c, 10, self.now), "next_ticket")
        self.assertTrue(waiting)
        self.assertIn("دعوت فعال کافی", text)
        self.assertEqual(activation_keyboard("https://t.me/TestBot?start=ref", label, waiting).inline_keyboard[0][0].callback_data, "menu:stats")
        self.one_ticket(20, qualified=3)
        self.assertEqual(activation_message(self.c, self.db.campaign_counts(self.c, 20, self.now), "next_ticket")[1], "📤 دعوت ۱ دوست دیگر")

    def test_late_pending_is_not_promised_as_next_ticket_progress(self):
        self.one_ticket()
        self.join(10, self.c.final_qualification_cutoff + timedelta(hours=1))
        counts = self.db.campaign_counts(self.c, 10, self.now)
        self.assertEqual(counts["qualifiable_pending"], 0)
        self.assertEqual(activation_message(self.c, counts, "next_ticket")[1], "📤 دعوت ۲ دوست دیگر")

    def test_audience_is_immutable_and_claim_survives_restart_and_concurrent_attempts(self):
        self.one_ticket()
        self.holder(20)
        self.assertTrue(start_run(self.db, self.c, "next_ticket", 999, [10], self.now))
        self.assertFalse(start_run(self.db, self.c, "next_ticket", 998, [20], self.now + timedelta(hours=1)))
        baseline = activity_snapshot(self.db, self.c, 10, self.now)
        self.db.init()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: claim_recipient(ReferralDB(self.path), self.c, "next_ticket", 10, baseline), range(2)))
        self.assertEqual(claims.count(True), 1)
        self.assertEqual(pending_recipients(self.db, self.c.id, "next_ticket"), [])
        self.assertEqual(activation_report(self.db, self.c, "next_ticket")["states"], {"sending": 1})

    async def test_delivery_once_direct_share_and_existing_funnel_unchanged(self):
        self.one_ticket()
        with self.db.connect() as conn:
            before = conn.execute(
                "SELECT event_type,user_id,source,created_at FROM funnel_events WHERE campaign_id=? ORDER BY 1,2,3",
                (self.c.id,),
            ).fetchall()
        await self.run_sender()
        await self.run_sender()
        self.assertEqual(len(self.recipient_calls()), 1)
        button = self.recipient_calls()[0].kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(parse_qs(urlparse(button.url).query)["url"], [f"https://t.me/TestBot?start=ref_{self.c.id}_user10"])
        with self.db.connect() as conn:
            after = conn.execute(
                "SELECT event_type,user_id,source,created_at FROM funnel_events WHERE campaign_id=? AND event_type!='activation_campaign_sent' ORDER BY 1,2,3",
                (self.c.id,),
            ).fetchall()
        self.assertEqual([tuple(row) for row in before], [tuple(row) for row in after])
        self.assertTrue(self.db.has_funnel_event(self.c.id, 10, "activation_campaign_sent", "next_ticket"))

    async def test_first_friend_send_is_separate_with_correct_one_friend_goal(self):
        self.holder(10)
        await self.run_sender("first_friend")
        call = self.recipient_calls()[0]
        self.assertIn("یک دوست", call.args[1])
        self.assertIn("۲ دعوت فعال", call.args[1])
        self.assertEqual(call.kwargs["reply_markup"].inline_keyboard[0][0].text, "📤 دعوت اولین دوست")
        self.assertIsNone(get_run(self.db, self.c.id, "next_ticket"))

    async def test_changed_progress_after_preview_is_skipped(self):
        self.one_ticket()
        start_run(self.db, self.c, "next_ticket", 999, [10], self.now)
        self.join(10)
        self.join(10)
        with patch("telegram_bot.activation_campaigns.asyncio.sleep", new=AsyncMock()):
            await send_activation_campaign(self.app, self.c.id, "next_ticket", "TestBot", 999)
        self.assertEqual(self.recipient_calls(), [])
        self.assertEqual(activation_report(self.db, self.c, "next_ticket")["states"], {"skipped": 1})

    async def test_failure_and_uncertain_timeout_are_not_retried_or_reported_as_delivered(self):
        self.one_ticket(10)
        self.one_ticket(20)
        async def send(uid, *args, **kwargs):
            if uid == 10:
                raise Forbidden("blocked")
            if uid == 20:
                raise TimedOut("unknown delivery")
            return SimpleNamespace(message_id=1, date=self.now)
        self.bot.send_message.side_effect = send
        await self.run_sender(user_ids=[10, 20])
        await self.run_sender(user_ids=[10, 20])
        self.assertEqual(len(self.recipient_calls(10)), 1)
        self.assertEqual(len(self.recipient_calls(20)), 1)
        r = activation_report(self.db, self.c, "next_ticket")
        self.assertEqual(r["states"], {"failed": 1, "unknown": 1})
        self.assertFalse(self.db.has_funnel_event(self.c.id, 10, "activation_campaign_sent", "next_ticket"))

    async def test_crash_during_send_is_never_automatically_resent(self):
        self.one_ticket()
        async def send(uid, *args, **kwargs):
            if uid == 10:
                raise asyncio.CancelledError()
            return SimpleNamespace(message_id=1, date=self.now)
        self.bot.send_message.side_effect = send
        with self.assertRaises(asyncio.CancelledError):
            await self.run_sender()
        self.db.init()
        await self.run_sender()
        self.assertEqual(len(self.recipient_calls()), 1)
        self.assertEqual(activation_report(self.db, self.c, "next_ticket")["states"], {"sending": 1})

    async def test_explicit_rate_limit_can_retry_without_duplicate_delivery(self):
        self.one_ticket()
        attempts = 0
        async def send(uid, *args, **kwargs):
            nonlocal attempts
            if uid == 10:
                attempts += 1
                if attempts == 1:
                    raise RetryAfter(0)
            return SimpleNamespace(message_id=1, date=self.now)
        self.bot.send_message.side_effect = send
        await self.run_sender()
        self.assertEqual(attempts, 2)
        self.assertEqual(activation_report(self.db, self.c, "next_ticket")["states"], {"sent": 1})

    async def test_notification_throttle_is_respected(self):
        self.one_ticket()
        for _ in range(5):
            self.db.notification_gate(self.c.id, 10, 5, 600)
        await self.run_sender()
        self.assertEqual(self.recipient_calls(), [])
        self.assertEqual(activation_report(self.db, self.c, "next_ticket")["states"], {"skipped": 1})

    def test_report_excludes_preexisting_candidates_self_future_and_other_campaign_activity(self):
        self.one_ticket()
        self.open(10, 101, self.now - timedelta(hours=1))
        self.db.upsert_user(102, None, "Pending")
        self.db.create_pending_referral(self.c, 102, 10, None, "Pending", self.now - timedelta(hours=1))
        start_run(self.db, self.c, "next_ticket", 999, [10], self.now)
        claim_recipient(self.db, self.c, "next_ticket", 10, activity_snapshot(self.db, self.c, 10, self.now), self.now)
        delivery = self.now + timedelta(minutes=1)
        finish_recipient(self.db, self.c.id, "next_ticket", 10, "sent", message_id=1, now=delivery)
        self.open(10, 201, delivery - timedelta(seconds=1))
        self.open(10, 202, delivery + timedelta(seconds=1))
        self.open(10, 202, delivery + timedelta(seconds=2))
        self.open(10, 10, delivery + timedelta(seconds=1))
        self.open(10, 9999, delivery + timedelta(days=10))
        self.db.finalize_pending_join(self.c, 102, None, "Pending", delivery + timedelta(seconds=1))
        self.join(10, delivery + timedelta(seconds=2), uid=202)
        self.join(10, delivery - timedelta(seconds=1), uid=201)
        other = self.db.create_campaign("other", "Other", self.now - timedelta(days=1), self.now + timedelta(days=10), "prizes")
        self.open(10, 9998, delivery, other.id)
        r = activation_report(self.db, self.c, "next_ticket", delivery + timedelta(days=1))
        self.assertEqual((r["with_new_open"], r["new_opens"], r["with_new_join"], r["new_joins"]), (1, 1, 1, 1))
        self.assertEqual(r["with_more_tickets_now"], 0)
        self.assertEqual(activation_report(self.db, self.c, "next_ticket", delivery + timedelta(days=8))["with_more_tickets_now"], 1)

    async def test_preview_is_admin_private_read_only_and_personalized(self):
        self.one_ticket()
        self.context.args = ["next_ticket"]
        self.update.effective_user.id = 888
        await cmd_activation_preview(self.update, self.context)
        self.message.reply_text.assert_not_awaited()
        self.update.effective_user.id = 999
        self.update.effective_chat.type = ChatType.GROUP
        await cmd_activation_preview(self.update, self.context)
        self.assertNotIn("activation_previews", self.app.bot_data)
        self.update.effective_chat.type = ChatType.PRIVATE
        await cmd_activation_preview(self.update, self.context)
        self.assertIsNone(get_run(self.db, self.c.id, "next_ticket"))
        self.bot.send_message.assert_not_awaited()
        self.assertIn("مخاطبان واجد شرایط: 1", self.message.reply_text.await_args_list[-2].args[0])
        self.assertIn("۲ دعوت فعال دیگر", self.message.reply_text.await_args_list[-1].args[0])

    async def test_confirmation_guards_owner_expiry_cancel_and_duplicate_callbacks(self):
        self.one_ticket()
        query = self.preview(admin=998)
        await on_activation_callback(self.update, self.context)
        self.assertIsNone(get_run(self.db, self.c.id, "next_ticket"))
        query = self.preview(expires=time.time() - 1)
        await on_activation_callback(self.update, self.context)
        self.assertIsNone(get_run(self.db, self.c.id, "next_ticket"))
        query = self.preview()
        query.data = "activate:no:testtoken"
        await on_activation_callback(self.update, self.context)
        self.assertIsNone(get_run(self.db, self.c.id, "next_ticket"))
        query = self.preview()
        with patch("telegram_bot.activation_campaigns.asyncio.sleep", new=AsyncMock()):
            await asyncio.gather(on_activation_callback(self.update, self.context), on_activation_callback(self.update, self.context))
            await asyncio.gather(*self.tasks)
        self.assertEqual(len(self.recipient_calls()), 1)

    async def test_report_command_is_read_only_admin_guarded_and_works_after_campaign_closes(self):
        self.one_ticket()
        await self.run_sender()
        self.update.effective_user.id = 888
        await cmd_activation_report(self.update, self.context)
        self.message.reply_text.assert_not_awaited()
        with self.db.connect() as conn:
            conn.execute("UPDATE campaigns SET status='closed' WHERE id=?", (self.c.id,))
        self.update.effective_user.id = 999
        self.context.args = [self.c.slug]
        await cmd_activation_report(self.update, self.context)
        text = "\n".join(call.args[0] for call in self.message.reply_text.await_args_list)
        self.assertIn("delivered=1", text)
        self.assertIn("first_friend: not launched", text)


if __name__ == "__main__":
    unittest.main()
