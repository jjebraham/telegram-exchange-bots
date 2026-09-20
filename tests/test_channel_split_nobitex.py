import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from nobitex_usdt import build_nobitex_usdt_post, parse_nobitex_usdt_stats  # noqa: E402


class NobitexUsdtTests(unittest.TestCase):
    def test_parse_public_market_stats(self):
        payload = {
            "status": "ok",
            "stats": {
                "usdt-rls": {
                    "isClosed": False,
                    "bestSell": "2296560",
                    "bestBuy": "2291200",
                    "latest": "2294000",
                    "dayHigh": "2301000",
                    "dayLow": "2265000",
                    "dayChange": "1.14",
                }
            },
        }

        quote = parse_nobitex_usdt_stats(payload)
        self.assertEqual(quote.best_sell_toman, Decimal("229656"))
        self.assertEqual(quote.best_buy_toman, Decimal("229120"))
        self.assertEqual(quote.day_change_pct, Decimal("1.14"))

        post = build_nobitex_usdt_post(quote)
        self.assertIn("<code>229,656</code>", post)
        self.assertIn("<code>229,120</code>", post)
        self.assertIn("1.14%", post)

    def test_missing_market_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_nobitex_usdt_stats({"status": "ok", "stats": {}})

    def test_closed_market_fails_closed(self):
        payload = {
            "status": "ok",
            "stats": {
                "usdt-rls": {
                    "isClosed": True,
                    "bestSell": "1",
                    "bestBuy": "1",
                    "latest": "1",
                    "dayHigh": "1",
                    "dayLow": "1",
                    "dayChange": "0",
                }
            },
        }
        with self.assertRaises(ValueError):
            parse_nobitex_usdt_stats(payload)


if __name__ == "__main__":
    unittest.main()
