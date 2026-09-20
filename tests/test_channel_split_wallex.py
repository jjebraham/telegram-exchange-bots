import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from wallex_usdt import build_wallex_usdt_post, parse_wallex_usdt_market  # noqa: E402


class WallexUsdtTests(unittest.TestCase):
    def test_parse_public_markets(self):
        payload = {
            "success": True,
            "result": {
                "symbols": {
                    "USDTTMN": {
                        "symbol": "USDTTMN",
                        "stats": {
                            "bidPrice": "229100",
                            "askPrice": "229650",
                            "24h_ch": "1.21",
                            "24h_highPrice": "231000",
                            "24h_lowPrice": "226800",
                            "lastPrice": "229500",
                        },
                    }
                }
            },
        }

        quote = parse_wallex_usdt_market(payload)
        self.assertEqual(quote.best_ask_toman, Decimal("229650"))
        self.assertEqual(quote.best_bid_toman, Decimal("229100"))
        self.assertEqual(quote.last_toman, Decimal("229500"))
        self.assertEqual(quote.change_24h_pct, Decimal("1.21"))

        post = build_wallex_usdt_post(quote)
        self.assertIn("<code>229,650</code>", post)
        self.assertIn("<code>229,100</code>", post)
        self.assertIn("<code>550</code>", post)
        self.assertIn("1.21%", post)

    def test_missing_usdt_market_fails_closed(self):
        payload = {"success": True, "result": {"symbols": {}}}
        with self.assertRaises(ValueError):
            parse_wallex_usdt_market(payload)

    def test_missing_bid_or_ask_fails_closed(self):
        payload = {
            "success": True,
            "result": {
                "symbols": {
                    "USDTTMN": {
                        "stats": {
                            "bidPrice": "229100",
                            "askPrice": None,
                            "24h_ch": "0",
                            "24h_highPrice": "230000",
                            "24h_lowPrice": "228000",
                            "lastPrice": "229500",
                        }
                    }
                }
            },
        }
        with self.assertRaises(ValueError):
            parse_wallex_usdt_market(payload)


if __name__ == "__main__":
    unittest.main()
