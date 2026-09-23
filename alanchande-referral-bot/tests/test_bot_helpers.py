import unittest
from types import SimpleNamespace

from telegram.constants import ChatMemberStatus

from telegram_bot.config import Settings, chat_member_is_active, is_configured_channel


class BotHelperTests(unittest.TestCase):
    def settings(self, channel="-100123"):
        return Settings(
            bot_token="fake",
            channel_id_raw=channel,
            channel_url="https://t.me/alanchande_com",
            admin_ids=frozenset({1}),
            db_path=":memory:",
        )

    def test_channel_matching_numeric(self):
        self.assertTrue(is_configured_channel(SimpleNamespace(id=-100123, username=None), self.settings()))
        self.assertFalse(is_configured_channel(SimpleNamespace(id=-100999, username=None), self.settings()))

    def test_channel_matching_username(self):
        settings = self.settings("@AlanChande_Com")
        self.assertTrue(is_configured_channel(SimpleNamespace(id=-1, username="alanchande_com"), settings))
        self.assertFalse(is_configured_channel(SimpleNamespace(id=-1, username="other"), settings))

    def test_active_membership_status(self):
        self.assertTrue(chat_member_is_active(SimpleNamespace(status=ChatMemberStatus.MEMBER)))
        self.assertFalse(chat_member_is_active(SimpleNamespace(status=ChatMemberStatus.LEFT)))
        self.assertTrue(chat_member_is_active(SimpleNamespace(status=ChatMemberStatus.RESTRICTED, is_member=True)))


if __name__ == "__main__":
    unittest.main()
