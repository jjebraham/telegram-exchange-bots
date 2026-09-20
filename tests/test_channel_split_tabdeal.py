import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from tabdeal_usdt import build_tabdeal_usdt_post, parse_tabdeal_usdt_depth  # noqa: E402


class TabdealUsdtTests(unittest.TestCase):
    def test_parse_public_depth(self):
        payload = {
            "bids": [["228500.0", "125.75"]],
            "asks": [["228750.0", "87.50"]],
        }

        quote = parse_tabdeal_usdt_depth(payload)
        self.assertEqual(quote.best_bid_toman, Decimal("228500.0"))
        self.assertEqual(quote.best_ask_toman, Decimal("228750.0"))
        self.assertEqual(quote.best_bid_quantity, Decimal("125.75"))
        self.assertEqual(quote.best_ask_quantity, Decimal("87.50"))

        post = build_tabdeal_usdt_post(quote)
        self.assertIn("<code>228,750</code>", post)
        self.assertIn("<code>228,500</code>", post)
        self.assertIn("<code>250</code>", post)

    def test_missing_asks_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_tabdeal_usdt_depth({"bids": [["1", "1"]], "asks": []})

    def test_crossed_book_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_tabdeal_usdt_depth(
                {
                    "bids": [["229000", "1"]],
                    "asks": [["228000", "1"]],
                }
            )


if __name__ == "__main__":
    unittest.main()
