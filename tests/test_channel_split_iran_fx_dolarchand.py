"""Regression tests for Dolarchand as a third Iran-FX verifier."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from channel_split.iran_fx_dolarchand import parse_dolarchand_toman_rate
from channel_split.market_safety import SafetyObservation, VERIFIED, evaluate_observation


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "channel_split" / "publish_channels.py"


class IranFxDolarchandTests(unittest.TestCase):
    def test_parse_explicit_toman_sell_rate(self):
        html = """
        <html><body>
        <div>Sell rate for Azerbaijani Manat to Toman 138,400</div>
        </body></html>
        """
        self.assertEqual(
            parse_dolarchand_toman_rate(html),
            Decimal("138400"),
        )

    def test_azn_three_source_consensus_verifies(self):
        check = evaluate_observation(
            SafetyObservation(
                market_key="iran-fx:AZN/TOMAN",
                source_values={
                    "tgju": Decimal("138510"),
                    "pashizi": Decimal("135800"),
                    "dolarchand": Decimal("138400"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("6.00"),
                strong_quorum=3,
            )
        )
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(check.reference_value, Decimal("138400"))

    def test_try_unique_three_of_four_cluster_rejects_adonis_outlier(self):
        check = evaluate_observation(
            SafetyObservation(
                market_key="iran-fx:TRY/TOMAN",
                source_values={
                    "tgju": Decimal("4896.5"),
                    "pashizi": Decimal("4815"),
                    "dolarchand": Decimal("4880"),
                    "adonis": Decimal("4769"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("6.00"),
                strong_quorum=3,
            )
        )
        self.assertEqual(check.decision, VERIFIED)
        self.assertEqual(check.reference_value, Decimal("4880"))
        self.assertEqual(
            set(check.source_values),
            {"tgju", "pashizi", "dolarchand"},
        )
        self.assertIn("rejected outlier source(s): adonis=4769", check.reason)

    def test_ambiguous_two_vs_two_split_remains_blocked(self):
        check = evaluate_observation(
            SafetyObservation(
                market_key="iran-fx:TEST/TOMAN",
                source_values={
                    "a": Decimal("100"),
                    "b": Decimal("100.5"),
                    "c": Decimal("104"),
                    "d": Decimal("104.5"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("6.00"),
                strong_quorum=3,
            )
        )
        self.assertNotEqual(check.decision, VERIFIED)

    def test_two_source_disagreement_still_blocks(self):
        check = evaluate_observation(
            SafetyObservation(
                market_key="iran-fx:AZN/TOMAN",
                source_values={
                    "tgju": Decimal("140000"),
                    "pashizi": Decimal("136000"),
                },
                min_sources=2,
                max_source_deviation_pct=Decimal("2.00"),
                suspicious_move_pct=Decimal("6.00"),
                strong_quorum=3,
            )
        )
        self.assertNotEqual(check.decision, VERIFIED)

    def test_publisher_wires_optional_dolarchand_source(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn("fetch_dolarchand_iran_fx", text)
        self.assertIn('source_values["dolarchand"] = dolarchand[code]', text)
        self.assertIn('"iran:dolarchand-fx"', text)


if __name__ == "__main__":
    unittest.main()
