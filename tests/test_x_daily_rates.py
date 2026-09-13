import unittest
from decimal import Decimal

from x_daily_rates import build_post_text


class DailyXRatesTests(unittest.TestCase):
    def setUp(self):
        self.rates = {
            "buy_lira": Decimal("4910"),
            "sell_lira": Decimal("4690"),
            "buy_usdt": Decimal("236370"),
            "sell_usdt": Decimal("231690"),
            "lira_to_usdt": Decimal("49.63"),
            "usdt_to_lira": Decimal("47.69"),
        }

    def test_post_matches_customer_rate_direction_and_format(self):
        text = build_post_text(self.rates)
        self.assertIn("🇹🇷 فروش لیر به شما: 4,910", text)
        self.assertIn("🇹🇷 خرید لیر از شما: 4,690", text)
        self.assertIn("🪙 فروش تتر به شما: 236,370", text)
        self.assertIn("🪙 خرید تتر از شما: 231,690", text)
        self.assertIn("💲 لیر به تتر: 49.63", text)
        self.assertIn("💲 تتر به لیر: 47.69", text)

    def test_whatsapp_link_is_included(self):
        text = build_post_text(self.rates)
        self.assertIn("https://wa.me/905411603664", text)
        self.assertNotIn("+905411603664", text)

    def test_miniapp_link_is_included_by_default(self):
        text = build_post_text(self.rates)
        self.assertTrue(text.endswith("https://miniapp.kiani.exchange"))

    def test_miniapp_link_can_be_omitted_without_removing_whatsapp(self):
        text = build_post_text(self.rates, include_link=False)
        self.assertNotIn("miniapp.kiani.exchange", text)
        self.assertIn("https://wa.me/905411603664", text)


if __name__ == "__main__":
    unittest.main()
