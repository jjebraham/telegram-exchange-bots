"""Offline parser and safety tests for the read-only stage-2 digest probe."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from daily_digest_stage2_probe import (  # noqa: E402
    consensus,
    parse_binance_prices,
    parse_dolarchand_sell_toman,
    parse_gold_api,
    parse_okx_prices,
    parse_tgju_profile_current,
    parse_txe_iqd100_toman,
)


class StageTwoDigestProbeTests(unittest.TestCase):
    def test_dolarchand_sell_toman_parser(self):
        html = """
        <html><body>
          <div>Sell rate for US Dollar to Toman</div>
          <strong>232,900</strong>
        </body></html>
        """
        self.assertEqual(parse_dolarchand_sell_toman(html), Decimal("232900"))

    def test_tgju_profile_current_parser(self):
        html = "<div>نرخ فعلی:: 1,490 -</div>"
        self.assertEqual(parse_tgju_profile_current(html), Decimal("1490"))

    def test_txe_iqd_midpoint_converts_to_100_iqd(self):
        html = """
        <table><tr>
          <td>دینار عراق</td><td>147</td><td>149</td>
        </tr></table>
        """
        self.assertEqual(parse_txe_iqd100_toman(html), Decimal("14800"))

    def test_gold_api_parser(self):
        quote = parse_gold_api({
            "price": 4350.6,
            "updatedAt": "2026-09-24T00:01:02Z",
        })
        self.assertEqual(quote.price, Decimal("4350.6"))
        self.assertIsNotNone(quote.updated_at)

    def test_binance_price_parser(self):
        prices = parse_binance_prices([
            {"symbol": "BTCUSDT", "lastPrice": "81000.10"},
            {"symbol": "ETHUSDT", "lastPrice": "2600.20"},
            {"symbol": "FOOUSDT", "lastPrice": "1"},
        ])
        self.assertEqual(prices["BTC"], Decimal("81000.10"))
        self.assertEqual(prices["ETH"], Decimal("2600.20"))
        self.assertNotIn("FOO", prices)

    def test_okx_price_parser(self):
        prices = parse_okx_prices({
            "data": [
                {"instId": "BTC-USDT", "last": "81001.10"},
                {"instId": "ETH-USDT", "last": "2601.20"},
                {"instId": "FOO-USDT", "last": "1"},
            ]
        })
        self.assertEqual(prices["BTC"], Decimal("81001.10"))
        self.assertEqual(prices["ETH"], Decimal("2601.20"))
        self.assertNotIn("FOO", prices)

    def test_consensus_requires_two_sources(self):
        decision, ref, _ = consensus("BTC", {"binance": Decimal("81000")})
        self.assertEqual(decision, "BLOCKED")
        self.assertEqual(ref, Decimal("81000"))

    def test_consensus_accepts_close_sources(self):
        decision, ref, _ = consensus(
            "BTC",
            {"binance": Decimal("81000"), "okx": Decimal("81100")},
        )
        self.assertEqual(decision, "VERIFIED")
        self.assertEqual(ref, Decimal("81050"))

    def test_consensus_blocks_large_disagreement(self):
        decision, _, _ = consensus(
            "100 IQD",
            {"tgju": Decimal("14900"), "other": Decimal("17750")},
        )
        self.assertEqual(decision, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
