import unittest
from datetime import datetime, timedelta, timezone
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

    def test_ticket_holder_share_ctas_name_the_next_two_friends(self):
        campaign = SimpleNamespace(
            slug="paeez1405",
            name="پاییز ۱۴۰۵",
            num_winners=5,
            invites_per_point=2,
            max_points=20,
            final_qualification_cutoff=datetime.now(timezone.utc) + timedelta(days=30),
        )
        counts = {"active": 2, "current_points": 1, "confirmed_points": 1}
        link = "https://t.me/Alanchandebot?start=ref_6_example"

        main = ui.main_keyboard(self.settings(), campaign, counts)
        leaderboard = ui.leaderboard_keyboard(link, campaign, counts)
        share = ui.link_keyboard(self.settings(), link, campaign, counts)

        self.assertEqual(main.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")
        self.assertEqual(leaderboard.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")
        self.assertEqual(share.inline_keyboard[0][0].text, "📤 دعوت ۲ دوست دیگر")

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
