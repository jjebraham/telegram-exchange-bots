import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from ramzinex_usdt import (  # noqa: E402
    build_ramzinex_usdt_post,
    parse_ramzinex_usdt_orderbook,
    parse_ramzinex_usdt_pair_id,
)


class RamzinexUsdtTests(unittest.TestCase):
    def test_parse_usdt_irr_pair_id(self):
        payload = {
            "status": 0,
            "data": [
                {
                    "pair_id": 11,
                    "base_currency_symbol": {"en": "usdt", "fa": "تتر"},
                    "quote_currency_symbol": {"en": "irr", "fa": "ریال"},
                    "is_delist": 0,
                    "is_temporarily_suspended": 0,
                }
            ],
        }

        self.assertEqual(parse_ramzinex_usdt_pair_id(payload), 11)

    def test_parse_orderbook_converts_rial_to_toman(self):
        payload = {
            "status": 0,
            "data": {
                "buys": [
                    ["2281000", "15"],
                    ["2283000", "12.5"],
                ],
                "sells": [
                    ["2289000", "8"],
                    ["2287000", "11.25"],
                ],
            },
        }

        quote = parse_ramzinex_usdt_orderbook(11, payload)
        self.assertEqual(quote.best_bid_toman, Decimal("228300"))
        self.assertEqual(quote.best_ask_toman, Decimal("228700"))
        self.assertEqual(quote.best_bid_quantity, Decimal("12.5"))
        self.assertEqual(quote.best_ask_quantity, Decimal("11.25"))

        post = build_ramzinex_usdt_post(quote)
        self.assertIn("<code>228,700</code>", post)
        self.assertIn("<code>228,300</code>", post)
        self.assertIn("<code>400</code>", post)

    def test_suspended_pair_is_rejected(self):
        payload = {
            "status": 0,
            "data": [
                {
                    "pair_id": 11,
                    "base_currency_symbol": {"en": "usdt"},
                    "quote_currency_symbol": {"en": "irr"},
                    "is_temporarily_suspended": 1,
                }
            ],
        }
        with self.assertRaises(ValueError):
            parse_ramzinex_usdt_pair_id(payload)


if __name__ == "__main__":
    unittest.main()
