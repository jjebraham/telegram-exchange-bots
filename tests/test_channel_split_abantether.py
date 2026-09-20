import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from abantether_usdt import (  # noqa: E402
    build_abantether_usdt_post,
    parse_abantether_usdt_ticker,
)


class AbanTetherUsdtTests(unittest.TestCase):
    def test_parse_public_ticker(self):
        payload = {
            "data": {
                "markets": {
                    "USDTIRT": {
                        "symbol": "USDT",
                        "buy_price": "229850.000",
                        "sell_price": "229400.000",
                        "buy_max": "10000.00",
                        "sell_max": "10000.00",
                        "active": True,
                    }
                }
            }
        }

        quote = parse_abantether_usdt_ticker(payload)
        self.assertEqual(quote.buy_toman, Decimal("229850.000"))
        self.assertEqual(quote.sell_toman, Decimal("229400.000"))
        self.assertEqual(quote.buy_max, Decimal("10000.00"))
        self.assertEqual(quote.sell_max, Decimal("10000.00"))

        post = build_abantether_usdt_post(quote)
        self.assertIn("<code>229,850</code>", post)
        self.assertIn("<code>229,400</code>", post)
        self.assertIn("<code>450</code>", post)

    def test_inactive_market_fails_closed(self):
        payload = {
            "data": {
                "markets": {
                    "USDTIRT": {
                        "symbol": "USDT",
                        "buy_price": "229850",
                        "sell_price": "229400",
                        "active": False,
                    }
                }
            }
        }
        with self.assertRaises(ValueError):
            parse_abantether_usdt_ticker(payload)

    def test_crossed_prices_fail_closed(self):
        payload = {
            "data": {
                "markets": {
                    "USDTIRT": {
                        "symbol": "USDT",
                        "buy_price": "229000",
                        "sell_price": "229100",
                        "active": True,
                    }
                }
            }
        }
        with self.assertRaises(ValueError):
            parse_abantether_usdt_ticker(payload)


if __name__ == "__main__":
    unittest.main()
