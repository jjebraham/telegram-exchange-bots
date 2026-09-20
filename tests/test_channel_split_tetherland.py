import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from tetherland_usdt import (  # noqa: E402
    build_tetherland_usdt_post,
    parse_tetherland_usdt,
)


class TetherlandUsdtTests(unittest.TestCase):
    def test_parse_reference_price(self):
        payload = {
            "data": {
                "currencies": {
                    "USDT": {
                        "price": 229650,
                        "diff24d": 0.42,
                        "last24h": 228690,
                    }
                }
            }
        }

        quote = parse_tetherland_usdt(payload)
        self.assertEqual(quote.price_toman, Decimal("229650"))
        self.assertEqual(quote.change_24h_pct, Decimal("0.42"))
        self.assertEqual(quote.last_24h_toman, Decimal("228690"))

        post = build_tetherland_usdt_post(quote)
        self.assertIn("<code>229,650</code>", post)
        self.assertIn("0.42%", post)
        self.assertIn("نرخ مرجع", post)
        self.assertIn("نه بهترین سفارش خرید/فروش", post)

    def test_missing_usdt_fails_closed(self):
        payload = {"data": {"currencies": {}}}
        with self.assertRaises(ValueError):
            parse_tetherland_usdt(payload)

    def test_invalid_price_fails_closed(self):
        payload = {
            "data": {
                "currencies": {
                    "USDT": {
                        "price": 0,
                    }
                }
            }
        }
        with self.assertRaises(ValueError):
            parse_tetherland_usdt(payload)


if __name__ == "__main__":
    unittest.main()
