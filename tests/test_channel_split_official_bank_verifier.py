import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from official_bank_verifier import (  # noqa: E402
    parse_isbank_midpoint,
    parse_ziraat_midpoint,
)


class OfficialBankVerifierTests(unittest.TestCase):
    def test_isbank_parses_official_bank_row(self):
        html = """
        <table>
          <tr><th>Döviz Cinsi</th><th>Banka Alış</th><th>Banka Satış</th></tr>
          <tr><td>USD Amerikan Doları</td><td>47,314</td><td>49,9294</td></tr>
          <tr><td>EUR Avrupa Para Birimi</td><td>54,9174</td><td>57,958</td></tr>
        </table>
        """
        self.assertEqual(
            parse_isbank_midpoint(html, "USD/TRY"),
            (Decimal("47.314") + Decimal("49.9294")) / Decimal("2"),
        )

    def test_ziraat_selects_official_channel_matching_displayed_row(self):
        html = """
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>48,2675</td><td>49,2893</td><td>48,1951</td><td>49,4372</td>
          </tr>
        </table>
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>47,3432</td><td>50,2255</td>
          </tr>
        </table>
        """
        primary = (Decimal("47.3432") + Decimal("50.2255")) / Decimal("2")
        self.assertEqual(
            parse_ziraat_midpoint(
                html,
                "USD/TRY",
                primary_midpoint=primary,
            ),
            primary,
        )

    def test_ziraat_rejects_page_when_no_channel_matches_displayed_rate(self):
        html = """
        <table>
          <tr>
            <td>USD</td><td>AMERIKAN DOLARI</td>
            <td>40,00</td><td>41,00</td>
          </tr>
        </table>
        """
        with self.assertRaisesRegex(ValueError, "matches"):
            parse_ziraat_midpoint(
                html,
                "USD/TRY",
                primary_midpoint=Decimal("49"),
                max_mapping_deviation_pct=Decimal("2"),
            )

    def test_missing_currency_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no usable"):
            parse_isbank_midpoint(
                "<table><tr><td>GBP</td><td>60,1</td><td>62,2</td></tr></table>",
                "USD/TRY",
            )


if __name__ == "__main__":
    unittest.main()
