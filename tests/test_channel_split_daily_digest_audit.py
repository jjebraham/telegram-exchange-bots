"""Offline checks of first-stage noon digest source audit."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from daily_digest_audit import CRYPTO, FX, GOLD, check_row  # noqa: E402


class DailyDigestAuditTests(unittest.TestCase):
    def test_requested_asset_inventory_is_complete(self):
        self.assertEqual(
            FX, ("USD", "EUR", "AED", "TRY", "CNY", "CAD", "AUD", "GBP", "AFN")
        )
        self.assertEqual(len(GOLD), 6)
        self.assertEqual(
            CRYPTO,
            ("BTC", "ETH", "BNB", "SHIB", "ADA", "DOGE", "TON", "NOT", "SOL", "XRP"),
        )

    def test_one_source_cannot_approve_a_price(self):
        result, value = check_row("USD", {"tgju": Decimal("230000")})
        self.assertEqual(result, "BLOCKED")
        self.assertEqual(value, "—")

    def test_two_agreeing_families_show_consensus(self):
        result, value = check_row("USD", {
            "tgju": Decimal("230000"), "pashizi": Decimal("230500")
        })
        self.assertEqual(result, "CONSENSUS")
        self.assertEqual(Decimal(value), Decimal("230250"))

    def test_two_disagreeing_families_are_blocked(self):
        result, value = check_row("USD", {
            "tgju": Decimal("230000"), "pashizi": Decimal("240000")
        })
        self.assertEqual(result, "BLOCKED")
        self.assertEqual(value, "—")

    def test_tenfold_unit_error_is_not_approved_by_source_check(self):
        result, _ = check_row("100 IQD", {
            "tgju": Decimal("10000"), "pashizi": Decimal("100000")
        })
        self.assertEqual(result, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
