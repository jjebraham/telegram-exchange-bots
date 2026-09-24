"""Offline parser/safety tests for stage-3 daily-digest probe."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from daily_digest_stage3_probe import (  # noqa: E402
    consensus,
    parse_bybit,
    parse_dolarchand_rate,
    parse_gate,
    parse_kucoin,
    parse_okx,
)


class StageThreeProbeTests(unittest.TestCase):
    def test_dolarchand_iqd_sell_rate(self):
        html = """
        <html><body>
        Sell rate for Iraqi Dinar to Toman
        14,880
        </body></html>
        """
        self.assertEqual(
            parse_dolarchand_rate(html, label_hint="Iraqi Dinar"),
            Decimal("14880"),
        )

    def test_dolarchand_xau_sell_rate(self):
        html = """
        <html><body>
        Sell rate for Gold Ounce (Global) to USD
        4,287.16
        </body></html>
        """
        self.assertEqual(
            parse_dolarchand_rate(html, label_hint="Gold Ounce (Global)"),
            Decimal("4287.16"),
        )

    def test_okx_parser(self):
        got = parse_okx({"data": [
            {"instId": "BTC-USDT", "last": "84345"},
            {"instId": "TON-USDT", "last": "1.60"},
        ]})
        self.assertEqual(got["BTC"], Decimal("84345"))
        self.assertEqual(got["TON"], Decimal("1.60"))

    def test_gate_parser(self):
        got = parse_gate([
            {"currency_pair": "BTC_USDT", "last": "84340"},
            {"currency_pair": "TON_USDT", "last": "1.59"},
        ])
        self.assertEqual(got["BTC"], Decimal("84340"))
        self.assertEqual(got["TON"], Decimal("1.59"))

    def test_kucoin_parser(self):
        got = parse_kucoin({"data": {"ticker": [
            {"symbol": "BTC-USDT", "last": "84341"},
            {"symbol": "NOT-USDT", "last": "0.00047"},
        ]}})
        self.assertEqual(got["BTC"], Decimal("84341"))
        self.assertEqual(got["NOT"], Decimal("0.00047"))

    def test_bybit_parser(self):
        got = parse_bybit({"result": {"list": [
            {"symbol": "BTCUSDT", "lastPrice": "84342"},
            {"symbol": "BNBUSDT", "lastPrice": "768.5"},
        ]}})
        self.assertEqual(got["BTC"], Decimal("84342"))
        self.assertEqual(got["BNB"], Decimal("768.5"))

    def test_consensus_accepts_two_close_direct_exchanges(self):
        decision, ref, _reason, accepted = consensus(
            "BTC",
            {"okx": Decimal("84345"), "gate": Decimal("84340")},
        )
        self.assertEqual(decision, "VERIFIED")
        self.assertEqual(ref, Decimal("84342.5"))
        self.assertEqual(set(accepted), {"okx", "gate"})

    def test_consensus_rejects_single_source(self):
        decision, _ref, _reason, accepted = consensus(
            "TON",
            {"gate": Decimal("1.60")},
        )
        self.assertEqual(decision, "BLOCKED")
        self.assertEqual(set(accepted), {"gate"})

    def test_consensus_can_reject_one_outlier_from_three(self):
        decision, ref, _reason, accepted = consensus(
            "XAU",
            {
                "tgju": Decimal("4287"),
                "gold-api": Decimal("4288"),
                "bad": Decimal("4500"),
            },
        )
        self.assertEqual(decision, "VERIFIED")
        self.assertEqual(ref, Decimal("4287.5"))
        self.assertEqual(set(accepted), {"tgju", "gold-api"})


if __name__ == "__main__":
    unittest.main()
