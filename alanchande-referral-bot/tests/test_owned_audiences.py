import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from referral_core import ReferralDB
from telegram_bot.growth import build_promo_link, cmd_promo_post, promo_post_text, source_performance
from telegram_bot.owned_audiences import OWNED_AUDIENCES, cmd_owned_sources
from telegram_bot.promo_handlers import cmd_start_entry
from telegram_bot.reporting import reply_report
from telegram_bot.share_activation import cmd_sources, record_referral_open_received


class OwnedAudienceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = ReferralDB(os.path.join(self.tmp.name, "test.db"))
        self.db.init()
        self.now = datetime.now(timezone.utc)
        campaign = self.db.create_campaign(
            "seed", "Seed", self.now - timedelta(days=1),
            self.now + timedelta(days=20), "Prizes",
            invites_per_point=2, min_stay_hours=168, max_points=20, num_winners=5,
        )
        self.db.activate_campaign(campaign.slug, self.now)
        self.campaign = self.db.get_campaign(campaign.slug)
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1, username="admin", first_name="Admin", last_name=None),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        self.context = SimpleNamespace(
            args=[], bot=SimpleNamespace(username="Alanchandebot", send_message=AsyncMock()),
            application=SimpleNamespace(bot_data={
                "settings": SimpleNamespace(admin_ids={1}, channel_url="https://t.me/alanchande_com"),
                "db": self.db,
            }),
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def output(self):
        return "\n".join(call.args[0] for call in self.update.message.reply_text.await_args_list)

    async def test_empty_dashboard_lists_all_links_without_writing_events(self):
        await cmd_owned_sources(self.update, self.context)
        text = self.output()
        for audience in OWNED_AUDIENCES:
            self.assertIn(f"?start=promo_{audience}_b", text)
            self.assertIn(f"/promo_post {audience} b", text)
        self.assertEqual(text.count("starts=0 entered=0"), 3)
        self.assertEqual(text.count("holder→open=n/a"), 3)
        self.assertEqual(source_performance(self.db, self.campaign)["rows"], [])
        self.context.bot.send_message.assert_not_awaited()

    async def test_admin_only_and_unknown_campaign(self):
        self.update.effective_user.id = 2
        await cmd_owned_sources(self.update, self.context)
        self.update.message.reply_text.assert_not_awaited()
        self.update.effective_user.id = 1
        self.context.args = ["missing"]
        await cmd_owned_sources(self.update, self.context)
        self.assertIn("Usage:", self.output())

    async def test_posts_use_exact_owned_source_links(self):
        for audience in OWNED_AUDIENCES:
            self.context.args = [audience, "b"]
            await cmd_promo_post(self.update, self.context)
            call = self.update.message.reply_text.await_args
            link = f"https://t.me/Alanchandebot?start=promo_{audience}_b"
            self.assertEqual(call.kwargs["reply_markup"].inline_keyboard[0][0].url, link)
            self.assertIn(link, call.args[0])
            self.assertIn("عضویت پیوسته", call.args[0])
            self.assertEqual(build_promo_link("Alanchandebot", f"{audience}_b", "b"), link)
        self.context.bot.send_message.assert_not_awaited()

    def test_owned_draft_uses_campaign_rules_and_escapes_campaign_content(self):
        campaign = SimpleNamespace(
            name="<Test>", prize_text="Prize & more", num_winners=3,
            invites_per_point=4, min_stay_hours=48,
            end_dt=self.now + timedelta(days=10),
            final_qualification_cutoff=self.now + timedelta(days=8),
        )
        text = promo_post_text(campaign, "https://t.me/test?start=promo_trstudy_b", "b", "trstudy_b")
        self.assertIn("TRStudy", text)
        self.assertIn("&lt;Test&gt;", text)
        self.assertIn("Prize &amp; more", text)
        self.assertIn("هر 4 دعوت فعال", text)
        self.assertIn("3 برنده", text)
        self.assertIn("2 روز", text)
        self.assertIn("یک دوست علاقه‌مند", text)

    def test_existing_mainchannel_and_variant_a_drafts_are_unchanged(self):
        for source, variant in (("mainchannel_b", "b"), ("meditation", "a"), ("other", "b")):
            link = build_promo_link("Alanchandebot", source, variant)
            self.assertEqual(promo_post_text(self.campaign, link, variant, source),
                             promo_post_text(self.campaign, link, variant))

    async def test_owned_starts_auto_enter_and_share_metrics_stay_separate(self):
        for uid, audience in enumerate(OWNED_AUDIENCES, 10):
            self.update.effective_user.id = uid
            self.context.args = [f"promo_{audience}_b"]
            with patch("telegram_bot.promo_handlers.telegram_membership", AsyncMock(return_value=True)):
                await cmd_start_entry(self.update, self.context)
            if uid == 10:
                record_referral_open_received(self.db, self.campaign.id, uid, 500)
                record_referral_open_received(self.db, self.campaign.id, uid, 500)
        rows = {r["source"]: r for r in source_performance(self.db, self.campaign)["rows"]}
        for audience in OWNED_AUDIENCES:
            row = rows[f"{audience}_b"]
            self.assertEqual((row["starts"], row["entered"], row["entry_auto_existing_member"]), (1, 1, 1))
        self.update.effective_user.id = 1
        self.context.args = ["seed"]
        self.update.message.reply_text.reset_mock()
        await cmd_owned_sources(self.update, self.context)
        self.assertIn("holders=1 with_open=1 unique_openers=1 | holder→open=100.0%", self.output())
        self.assertEqual(self.output().count("holders=1 with_open=0"), 2)

    async def test_later_owned_click_preserves_first_touch_and_legacy_tree(self):
        for uid in (10, 20, 30):
            self.db.upsert_user(uid, None, "User", now=self.now)
        self.db.track_funnel_event(self.campaign.id, 10, "bot_start", "meditation_b", self.now)
        self.db.save_invite_link(self.campaign.id, 10, "ref_seed_10", self.now)
        self.db.track_funnel_event(self.campaign.id, 10, "bot_start", "kriptofarsi_b", self.now + timedelta(seconds=1))
        self.db.save_invite_link(self.campaign.id, 20, "ref_seed_20", self.now - timedelta(days=1))
        self.db.track_funnel_event(self.campaign.id, 20, "bot_start", "trstudy_b", self.now)
        self.db.record_join(self.campaign, 30, 20, None, "User", self.now)
        rows = {r["source"]: r for r in source_performance(self.db, self.campaign)["rows"]}
        self.assertNotIn("kriptofarsi_b", rows)
        self.assertEqual(rows["meditation_b"]["links"], 1)
        self.assertEqual(rows["trstudy_b"]["links"], 0)
        self.assertEqual(rows["legacy/untracked"]["joins"], 1)

    async def test_sources_delivers_all_sources_in_bounded_messages(self):
        for uid in range(25):
            self.db.upsert_user(uid, None, "User", now=self.now)
            self.db.track_funnel_event(self.campaign.id, uid, "bot_start", f"audience_{uid}_b", self.now)
            self.db.save_invite_link(self.campaign.id, uid, f"ref_seed_{uid}", self.now)
        await cmd_sources(self.update, self.context)
        for uid in range(25):
            self.assertEqual(self.output().count(f"• audience_{uid}_b\n"), 2)
        for call in self.update.message.reply_text.await_args_list:
            self.assertLessEqual(len(call.args[0].encode("utf-16-le")) // 2, 4096)
            self.assertIsNone(call.kwargs["parse_mode"])

    async def test_report_splits_long_unicode_line_without_data_loss(self):
        text = "🎁" * 5000
        await reply_report(self.update.message, text)
        self.assertEqual("".join(c.args[0] for c in self.update.message.reply_text.await_args_list), text)
        for call in self.update.message.reply_text.await_args_list:
            self.assertLessEqual(len(call.args[0].encode("utf-16-le")) // 2, 4096)
