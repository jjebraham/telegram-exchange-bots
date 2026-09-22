import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from kiani_posts import build_kiani_try_post, gregorian_to_jalali  # noqa: E402


class KianiPostTests(unittest.TestCase):
    def test_known_gregorian_date_converts_to_jalali(self):
        self.assertEqual(gregorian_to_jalali(2026, 9, 21), (1405, 6, 30))

    def test_try_post_preserves_customer_buy_sell_semantics(self):
        rates = {
            "buy_lira": Decimal("4750"),
            "sell_lira": Decimal("4590"),
        }
        now = datetime(
            2026, 9, 21, 20, 30, 10,
            tzinfo=ZoneInfo("Europe/Istanbul"),
        )

        post = build_kiani_try_post(rates, now=now)

        self.assertIn("دوشنبه، 30 شهریور 1405 | 20:30:10", post)
        self.assertIn("🇹🇷 <b>نرخ لیر ترکیه</b>", post)
        self.assertIn("BUY   TL 4,750 = خرید لیر از ما", post)
        self.assertIn("SELL  TL 4,590 = فروش لیر به ما", post)
        self.assertIn("https://t.me/TL905411603664", post)
        self.assertIn("https://wa.me/905392905686", post)
        self.assertIn("💵 واحد: تومان 🇮🇷", post)


if __name__ == "__main__":
    unittest.main()
