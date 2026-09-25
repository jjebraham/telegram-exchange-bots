import unittest
from types import SimpleNamespace

from telegram_bot import ui


class LinkAccessUiTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(channel_url="https://t.me/alanchande_com")

    def campaign(self):
        return SimpleNamespace(
            slug="paeez1405",
            name="پاییز ۱۴۰۵",
            num_winners=5,
        )

    def test_main_menu_exposes_personal_link_directly(self):
        keyboard = ui.main_keyboard(self.settings())
        first = keyboard.inline_keyboard[0][0]

        self.assertEqual(first.text, "🔗 لینک دعوت من")
        self.assertEqual(first.callback_data, "menu:link")

    def test_standard_link_keyboard_has_share_and_copy_actions(self):
        link = "https://t.me/Alanchandebot?start=ref_6_example"
        keyboard = ui.link_keyboard(self.settings(), link, self.campaign())

        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 ارسال لینک برای دوستان")
        copy_button = keyboard.inline_keyboard[1][0]
        if ui.CopyTextButton is not None:
            self.assertEqual(copy_button.text, "📋 کپی لینک")
            self.assertEqual(copy_button.copy_text.text, link)
        else:
            self.assertEqual(copy_button.text, "🔗 نمایش لینک")
            self.assertEqual(copy_button.callback_data, "menu:link")

    def test_referral_activation_keyboard_keeps_one_friend_cta_and_copy(self):
        link = "https://t.me/Alanchandebot?start=ref_6_example"
        keyboard = ui.referral_activation_keyboard(
            self.settings(),
            link,
            self.campaign(),
        )

        self.assertEqual(keyboard.inline_keyboard[0][0].text, "📤 همین الان برای ۱ نفر")
        copy_button = keyboard.inline_keyboard[1][0]
        if ui.CopyTextButton is not None:
            self.assertEqual(copy_button.text, "📋 کپی لینک")
            self.assertEqual(copy_button.copy_text.text, link)
        else:
            self.assertEqual(copy_button.callback_data, "menu:link")


if __name__ == "__main__":
    unittest.main()
