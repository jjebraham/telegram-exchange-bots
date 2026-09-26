import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

from telegram.error import TelegramError
from telegram_bot.user_handlers import on_menu_callback


class LeaderboardShareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.campaign = SimpleNamespace(id=6, name="پاییز ۱۴۰۵", num_winners=5)
        self.db = Mock()
        self.db.live_campaign.return_value = self.campaign
        self.bot = SimpleNamespace(username="Alanchandebot", get_me=AsyncMock())
        self.context = SimpleNamespace(bot=self.bot, application=SimpleNamespace(bot_data={
            "settings": SimpleNamespace(), "db": self.db,
        }))
        self.query = SimpleNamespace(data="menu:top", answer=AsyncMock(), edit_message_text=AsyncMock())
        self.update = SimpleNamespace(callback_query=self.query, effective_user=SimpleNamespace(
            id=42, username="viewer", first_name="Viewer", last_name=None))

    async def open_top(self):
        with patch("telegram_bot.user_handlers.render_top", return_value="Leaderboard"), \
             patch("telegram_bot.user_handlers.get_or_create_link", new_callable=AsyncMock) as create:
            await on_menu_callback(self.update, self.context)
            create.assert_not_awaited()
        self.db.save_invite_link.assert_not_called()
        self.db.replace_invite_link.assert_not_called()
        self.db.track_funnel_event.assert_not_called()
        return self.query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard

    async def test_share_uses_viewers_personal_link_and_retains_back(self):
        self.db.get_invite_link.return_value = "ref_6_viewerSecret"
        keyboard = await self.open_top()
        self.db.get_invite_link.assert_called_once_with(6, 42)
        self.assertEqual(keyboard[0][0].text, "📤 دعوت از یک دوست")
        parts = urlparse(keyboard[0][0].url)
        self.assertEqual((parts.netloc, parts.path), ("t.me", "/share/url"))
        params = parse_qs(parts.query)
        self.assertEqual(params["url"], ["https://t.me/Alanchandebot?start=ref_6_viewerSecret"])
        self.assertIn(self.campaign.name, params["text"][0])
        self.assertEqual(keyboard[1][0].callback_data, "menu:main")

    async def test_missing_or_legacy_link_uses_membership_checked_link_screen(self):
        for payload in (None, "https://t.me/+oldInvite"):
            with self.subTest(payload=payload):
                self.db.get_invite_link.return_value = payload
                keyboard = await self.open_top()
                self.assertIsNone(keyboard[0][0].url)
                self.assertEqual(keyboard[0][0].callback_data, "menu:link")
        self.bot.get_me.assert_not_awaited()

    async def test_uncached_username_is_resolved_and_network_failure_keeps_leaderboard(self):
        self.db.get_invite_link.return_value = "ref_6_viewerSecret"
        self.bot.username = None
        self.bot.get_me.return_value = SimpleNamespace(username="Alanchandebot")
        keyboard = await self.open_top()
        self.assertIn("Alanchandebot", keyboard[0][0].url)
        self.bot.get_me.side_effect = TelegramError("offline")
        keyboard = await self.open_top()
        self.assertEqual(keyboard[0][0].callback_data, "menu:link")
        self.assertEqual(self.query.edit_message_text.await_args.args[0], "Leaderboard")
