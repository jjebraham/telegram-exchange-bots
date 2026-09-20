import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from bitpin_usdt import (  # noqa: E402
    build_bitpin_usdt_post,
    parse_bitpin_usdt_market_id,
    parse_bitpin_usdt_orderbooks,
)


class BitpinUsdtTests(unittest.TestCase):
    def test_parse_market_id(self):
        payload = {
            "results": [
                {"id": 1, "code": "BTC_IRT"},
                {"id": 5, "code": "USDT_IRT"},
            ]
        }
        self.assertEqual(parse_bitpin_usdt_market_id(payload), 5)

    def test_parse_orderbooks_uses_best_prices(self):
        buy_payload = {
            "orders": [
                {"price": "228100", "amount": "10", "remain": "8"},
                {"price": "228300", "amount": "20", "remain": "15"},
            ],
            "volume": "23",
        }
        sell_payload = {
            "orders": [
                {"price": "228900", "amount": "12", "remain": "11"},
                {"price": "228700", "amount": "30", "remain": "25"},
            ],
            "volume": "36",
        }

        quote = parse_bitpin_usdt_orderbooks(5, buy_payload, sell_payload)
        self.assertEqual(quote.best_bid_toman, Decimal("228300"))
        self.assertEqual(quote.best_ask_toman, Decimal("228700"))
        self.assertEqual(quote.best_bid_quantity, Decimal("15"))
        self.assertEqual(quote.best_ask_quantity, Decimal("25"))

        post = build_bitpin_usdt_post(quote)
        self.assertIn("<code>228,700</code>", post)
        self.assertIn("<code>228,300</code>", post)
        self.assertIn("<code>400</code>", post)

    def test_crossed_book_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_bitpin_usdt_orderbooks(
                5,
                {"orders": [{"price": "229000", "amount": "1", "remain": "1"}]},
                {"orders": [{"price": "228000", "amount": "1", "remain": "1"}]},
            )


if __name__ == "__main__":
    unittest.main()
