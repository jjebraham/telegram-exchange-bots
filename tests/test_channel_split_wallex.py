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
                "markets": [
                    {
                        "symbol": "USDTTMN",
                        "price": "229500",
                        "change_24h": "1.21",
                        "is_spot": True,
                        "is_tmn_based": True,
                    }
                ]
            },
        }

        quote = parse_wallex_usdt_market(payload)
        self.assertEqual(quote.price_toman, Decimal("229500"))
        self.assertEqual(quote.change_24h_pct, Decimal("1.21"))

        post = build_wallex_usdt_post(quote)
        self.assertIn("<code>229,500</code>", post)
        self.assertIn("1.21%", post)
        self.assertIn("آخرین قیمت بازار", post)

    def test_missing_usdt_market_fails_closed(self):
        payload = {"success": True, "result": {"markets": []}}
        with self.assertRaises(ValueError):
            parse_wallex_usdt_market(payload)

    def test_non_spot_market_fails_closed(self):
        payload = {
            "success": True,
            "result": {
                "markets": [
                    {
                        "symbol": "USDTTMN",
                        "price": "229500",
                        "change_24h": "0",
                        "is_spot": False,
                        "is_tmn_based": True,
                    }
                ]
            },
        }
        with self.assertRaises(ValueError):
            parse_wallex_usdt_market(payload)


if __name__ == "__main__":
    unittest.main()
