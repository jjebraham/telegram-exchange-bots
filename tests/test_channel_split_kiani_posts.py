import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from kiani_posts import (  # noqa: E402
    build_kiani_rate_post,
    build_kiani_toman_receive_post,
    build_kiani_try_post,
    build_kiani_try_receive_post,
    gregorian_to_jalali,
)


class KianiPostTests(unittest.TestCase):
    def setUp(self):
        self.rates = {
            "buy_lira": Decimal("4770"),
            "sell_lira": Decimal("4600"),
            "buy_usdt": Decimal("227760"),
            "sell_usdt": Decimal("223240"),
            "lira_to_usdt": Decimal("49.59"),
            "usdt_to_lira": Decimal("47.65"),
        }

    def test_known_gregorian_date_converts_to_jalali(self):
        self.assertEqual(gregorian_to_jalali(2026, 9, 21), (1405, 6, 30))

    def test_try_post_uses_requested_buy_sell_style(self):
        now = datetime(
            2026, 9, 21, 20, 30, 10,
            tzinfo=ZoneInfo("Europe/Istanbul"),
        )

        post = build_kiani_try_post(self.rates, now=now)

        self.assertIn("دوشنبه، 30 شهریور 1405 | 20:30:10", post)
        self.assertIn("🇹🇷 <b>نرخ لیر ترکیه</b> به تومان 🇮🇷", post)
        self.assertIn("🟩 BUY   TL 4,770 = خرید لیر از ما", post)
        self.assertIn("🟥 SELL  TL 4,600 = فروش لیر به ما", post)
        self.assertIn("https://t.me/TL905411603664", post)
        self.assertIn("https://wa.me/905392905686", post)
        self.assertNotIn("واحد: تومان", post)

    def test_compact_rate_post_uses_customer_language(self):
        now = datetime(
            2026, 9, 22, 19, 8,
            tzinfo=ZoneInfo("Europe/Istanbul"),
        )
        post = build_kiani_rate_post(self.rates, now=now)

        self.assertIn("<b>صرافی کیانی | نرخ امروز</b>", post)
        self.assertNotIn("💱 <b>صرافی کیانی", post)
        self.assertIn("🟢 از ما می‌خرید: <b>4,770</b> تومان", post)
        self.assertIn("🔵 به ما می‌فروشید: <b>4,600</b> تومان", post)
        self.assertIn("🟢 از ما می‌خرید: <b>227,760</b> تومان", post)
        self.assertIn("🔵 به ما می‌فروشید: <b>223,240</b> تومان", post)
        self.assertIn("🔁 لیر ← تتر: <b>49.59</b> لیر", post)
        self.assertIn("🔁 تتر ← لیر: <b>47.65</b> لیر", post)
        self.assertIn("<code>19:08</code> استانبول", post)

    def test_try_receive_examples_use_fixed_ltr_table(self):
        post = build_kiani_try_receive_post(self.rates)

        self.assertIn(
            "برای دریافت این مقدار لیر چند تومان باید واریز بشود؟",
            post,
        )
        self.assertIn("<pre>", post)
        self.assertIn("TL", post)
        self.assertIn("TOMAN", post)
        self.assertNotIn("TRY", post)
        self.assertIn("در ایران 🇮🇷 تومان واریز می کنید", post)
        self.assertIn(
            "و معادل آن لیر ترکیه 🇹🇷 دریافت می کنید",
            post,
        )
        self.assertIn("10,000", post)
        self.assertIn("47,700,000", post)
        self.assertNotIn("≈", post)

    def test_toman_receive_examples_use_sell_lira_rate(self):
        post = build_kiani_toman_receive_post(self.rates)

        self.assertIn(
            "برای دریافت این مقدار تومان چند لیر باید واریز بشود؟",
            post,
        )
        self.assertIn("<pre>", post)
        self.assertNotIn("10,000,000", post)
        self.assertIn("50,000,000", post)
        self.assertIn("10,870", post)
        self.assertIn("100,000,000", post)
        self.assertIn("21,739", post)
        self.assertIn(
            "در ترکیه 🇹🇷 لیر واریز می کنید",
            post,
        )
        self.assertIn(
            "و معادل آن تومان در ایران 🇮🇷 دریافت می کنید",
            post,
        )
        self.assertIn("500,000,000", post)
        self.assertIn("108,700", post)
        self.assertIn("بر اساس نرخ خرید فعلی: <b>4,600</b> تومان", post)


if __name__ == "__main__":
    unittest.main()
