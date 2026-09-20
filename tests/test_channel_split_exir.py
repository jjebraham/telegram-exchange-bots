import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from exir_usdt import build_exir_usdt_post, parse_exir_usdt_orderbook  # noqa: E402


class ExirUsdtTests(unittest.TestCase):
    def test_parse_public_orderbook(self):
        payload = {
            "usdt-irt": {
                "bids": [[228100, 90.5], [228000, 20]],
                "asks": [[228300, 75.25], [228400, 30]],
                "timestamp": "2026-09-20T20:30:00.000Z",
            }
        }

        quote = parse_exir_usdt_orderbook(payload)
        self.assertEqual(quote.best_bid_toman, Decimal("228100"))
        self.assertEqual(quote.best_ask_toman, Decimal("228300"))
        self.assertEqual(quote.best_bid_quantity, Decimal("90.5"))
        self.assertEqual(quote.best_ask_quantity, Decimal("75.25"))
        self.assertEqual(
            quote.source_timestamp,
            "2026-09-20T20:30:00.000Z",
        )

        post = build_exir_usdt_post(quote)
        self.assertIn("<code>228,300</code>", post)
        self.assertIn("<code>228,100</code>", post)
        self.assertIn("<code>200</code>", post)
        self.assertIn("2026-09-20T20:30:00.000Z", post)

    def test_missing_market_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_exir_usdt_orderbook({})

    def test_crossed_book_fails_closed(self):
        payload = {
            "usdt-irt": {
                "bids": [[229000, 1]],
                "asks": [[228000, 1]],
            }
        }
        with self.assertRaises(ValueError):
            parse_exir_usdt_orderbook(payload)


if __name__ == "__main__":
    unittest.main()
