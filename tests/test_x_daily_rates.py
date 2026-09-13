import unittest
from decimal import Decimal

from x_daily_rates import build_post_text


class DailyXRatesTests(unittest.TestCase):
    def setUp(self):
        self.rates = {
            "buy_lira": Decimal("4670"),
            "sell_lira": Decimal("4450"),
            "buy_usdt": Decimal("227000"),
            "sell_usdt": Decimal("219000"),
            "lira_to_usdt": Decimal("49.95"),
            "usdt_to_lira": Decimal("46.70"),
        }

    def test_post_matches_customer_rate_direction(self):
        text = build_post_text(self.rates)
        self.assertIn("فروش لیر به شما: 4670", text)
        self.assertIn("خرید لیر از شما: 4450", text)
        self.assertIn("فروش تتر به شما: 227000", text)
        self.assertIn("خرید تتر از شما: 219000", text)
        self.assertIn("لیر به تتر: 49.95", text)
        self.assertIn("تتر به لیر: 46.7", text)

    def test_link_is_included_by_default(self):
        text = build_post_text(self.rates)
        self.assertTrue(text.endswith("https://miniapp.kiani.exchange"))

    def test_link_can_be_omitted(self):
        text = build_post_text(self.rates, include_link=False)
        self.assertNotIn("miniapp.kiani.exchange", text)


if __name__ == "__main__":
    unittest.main()
