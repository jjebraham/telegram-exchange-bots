"""Offline tests for corrected IQD and GRAM final-gap probe."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from daily_digest_stage4_probe import (  # noqa: E402
    consensus,
    parse_bitget_gram,
    parse_dolarchand_iqd100_toman,
    parse_gate_gram,
    parse_kucoin_gram,
    parse_okx_gram,
)


class StageFourProbeTests(unittest.TestCase):
    def test_dolarchand_iqd_parser_ignores_literal_100_heading_quantity(self):
        html = """
        <html><body>
        <h1>Iraqi Dinar</h1>
        <div>100 Iraqi Dinar</div>
        <div>Sell rate for 100 Iraqi Dinar to Toman</div>
        <strong>14,880</strong>
        </body></html>
        """
        self.assertEqual(
            parse_dolarchand_iqd100_toman(html),
            Decimal("14880"),
        )

    def test_okx_gram_parser(self):
        self.assertEqual(
            parse_okx_gram({"data": [{"instId": "GRAM-USDT", "last": "1.61"}]}),
            Decimal("1.61"),
        )

    def test_gate_gram_parser(self):
        self.assertEqual(
            parse_gate_gram([{"currency_pair": "GRAM_USDT", "last": "1.60"}]),
            Decimal("1.60"),
        )

    def test_kucoin_gram_parser(self):
        self.assertEqual(
            parse_kucoin_gram({
                "data": {"ticker": [{"symbol": "GRAM-USDT", "last": "1.59"}]}
            }),
            Decimal("1.59"),
        )

    def test_bitget_gram_parser(self):
        self.assertEqual(
            parse_bitget_gram({
                "data": [{"symbol": "GRAMUSDT", "lastPrice": "1.605"}]
            }),
            Decimal("1.605"),
        )

    def test_iqd_two_source_consensus(self):
        decision, ref, _reason, accepted = consensus(
            "100 IQD",
            {"tgju": Decimal("15090"), "dolarchand": Decimal("14880")},
        )
        self.assertEqual(decision, "VERIFIED")
        self.assertEqual(ref, Decimal("14985"))
        self.assertEqual(set(accepted), {"tgju", "dolarchand"})

    def test_gram_two_source_consensus(self):
        decision, ref, _reason, accepted = consensus(
            "GRAM",
            {"okx": Decimal("1.600"), "gate": Decimal("1.602")},
        )
        self.assertEqual(decision, "VERIFIED")
        self.assertEqual(ref, Decimal("1.601"))
        self.assertEqual(set(accepted), {"okx", "gate"})


if __name__ == "__main__":
    unittest.main()
