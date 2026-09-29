import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from referral_core import ReferralDB
from telegram_bot.launch_tracking import (
    mark_launch, launch_report, cmd_launch_mark, cmd_launch_report,
)


class LaunchTrackingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime.now(timezone.utc)
        self.start = self.now - timedelta(days=3)
        c = self.db.create_campaign("launch", "Launch", self.start - timedelta(days=2),
                                    self.now + timedelta(days=30), "Prizes")
        self.db.activate_campaign(c.slug, self.start)
        self.c = self.db.get_campaign(c.slug)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, uid, event, when, source="meditation_b"):
        self.db.upsert_user(uid, None, "User", now=self.start)
        self.db.track_funnel_event(self.c.id, uid, event, source, when)

    def holder(self, uid, when, source="meditation_b"):
        self.event(uid, "bot_start", when, source)
        self.event(uid, "entered_contest", when, source)
        self.db.save_invite_link(self.c.id, uid, f"ref_launch_{uid}", when)

    def marker(self, label="first", source="meditation_b"):
        return mark_launch(self.db, self.c, source, label, 1, self.start)

    def test_marker_is_immutable_with_persistent_baseline(self):
        self.holder(10, self.start - timedelta(hours=1))
        first, created = self.marker()
        self.assertTrue(created)
        self.assertEqual(json.loads(first["baseline_json"])["starts"], 1)
        second, created = mark_launch(self.db, self.c, "trstudy_b", "first", 2, self.now)
        self.assertFalse(created)
        self.assertEqual(first, second)
        self.db.init()
        self.assertEqual(launch_report(self.db, self.c.id, "first", self.now)["marker"], first)

    def test_24h_boundaries_pending_and_late_opens(self):
        self.marker()
        mature_at = self.now - timedelta(hours=24)
        self.holder(10, mature_at)
        self.event(10, "referral_open_received", self.now, "candidate:100")
        self.event(10, "referral_open_received", self.now, "candidate:100")
        self.holder(20, mature_at - timedelta(seconds=1))
        self.event(20, "referral_open_received", self.now, "candidate:200")  # too late
        self.holder(30, self.now - timedelta(hours=1))
        self.event(30, "referral_open_received", self.now, "candidate:300")
        self.holder(40, self.now - timedelta(minutes=1))
        r = launch_report(self.db, self.c.id, "first", self.now)
        self.assertEqual((r["starts"], r["entered"], r["holders"]), (4, 4, 4))
        self.assertEqual((r["mature"], r["activated_24h"]), (2, 1))
        self.assertEqual((r["pending"], r["pending_with_open"]), (2, 1))
        self.assertEqual((r["with_open"], r["unique_openers"]), (3, 3))

    def test_old_first_touch_returning_and_other_sources_excluded(self):
        self.marker()
        self.holder(10, self.start - timedelta(hours=1))
        self.event(10, "bot_start", self.now, "trstudy_b")
        self.event(20, "bot_start", self.start - timedelta(hours=1))
        self.event(20, "entered_contest", self.now)
        self.db.save_invite_link(self.c.id, 20, "ref_launch_20", self.now)
        self.holder(30, self.now, "organic")
        self.event(30, "bot_start", self.now + timedelta(seconds=1))
        self.event(40, "bot_start", self.now)
        self.db.save_invite_link(self.c.id, 40, "ref_launch_40", self.start - timedelta(days=1))
        self.event(50, "bot_start", self.now)
        r = launch_report(self.db, self.c.id, "first", self.now + timedelta(seconds=2))
        self.assertEqual((r["starts"], r["entered"], r["holders"]), (1, 0, 0))

    def test_only_valid_exact_opens_after_link_creation_count(self):
        self.marker(source="referral")
        when = self.now - timedelta(hours=25)
        self.holder(10, when, "referral")
        for source, at in [("candidate:10", self.now), ("candidate:bad", self.now),
                           ("candidate:100", when - timedelta(seconds=1)),
                           ("candidate:200", self.now + timedelta(seconds=1))]:
            self.event(10, "referral_open_received", at, source)
        self.event(100, "referral_open", self.now, "referral")
        r = launch_report(self.db, self.c.id, "first", self.now)
        self.assertEqual((r["starts"], r["mature"], r["activated_24h"], r["with_open"]), (1, 1, 0, 0))

    def test_marker_boundary_and_campaign_isolation(self):
        self.marker()
        self.holder(10, self.start)
        self.assertEqual(launch_report(self.db, self.c.id, "first", self.now)["starts"], 1)
        self.assertIsNone(launch_report(self.db, self.c.id + 1, "first", self.now))
        self.assertIsNone(launch_report(self.db, self.c.id, "missing", self.now))
        with self.assertRaises(ValueError):
            self.marker(label="invalid label")

    async def test_commands_admin_guard_usage_empty_rate_and_duplicate(self):
        update = SimpleNamespace(effective_user=SimpleNamespace(id=2),
                                 message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace(args=["meditation_b", "today"],
            application=SimpleNamespace(bot_data={"settings": SimpleNamespace(admin_ids={1}), "db": self.db}))
        await cmd_launch_mark(update, context)
        await cmd_launch_report(update, context)
        update.message.reply_text.assert_not_awaited()
        update.effective_user.id = 1
        await cmd_launch_mark(update, context)
        await cmd_launch_mark(update, context)
        self.assertIn("original marker preserved", update.message.reply_text.await_args.args[0])
        context.args = ["today", "launch"]
        await cmd_launch_report(update, context)
        output = "\n".join(c.args[0] for c in update.message.reply_text.await_args_list)
        self.assertIn("activation=n/a", output)
        self.assertIn("24h pending: holders=0", output)
        context.args = []
        await cmd_launch_mark(update, context)
        self.assertIn("Usage:", update.message.reply_text.await_args.args[0])
        await cmd_launch_report(update, context)
        self.assertIn("Usage:", update.message.reply_text.await_args.args[0])
