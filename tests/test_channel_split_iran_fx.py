import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_fx import CURRENCY_ROWS, build_iran_fx_post, parse_tgju_currency_page  # noqa: E402


class IranFxTests(unittest.TestCase):
    def _fixture_html(self, *, omit: str | None = None) -> str:
        values = {
            "USD": "2,286,000",
            "EUR": "2,624,000",
            "GBP": "3,061,000",
            "CHF": "2,779,000",
            "CAD": "1,633,000",
            "AUD": "1,628,000",
            "SEK": "232,000",
            "NOK": "242,000",
            "RUB": "27,170",
            "THB": "68,570",
            "SGD": "1,791,000",
            "HKD": "291,000",
            "AZN": "1,345,000",
            "DKK": "351,000",
            "AED": "622,000",
            "TRY": "46,890",
            "CNY": "341,000",
            "SAR": "608,000",
            "INR": "23,850",
            "MYR": "559,000",
            "AFN": "35,420",
            "KWD": "7,414,000",
            "BHD": "6,081,000",
            "OMR": "5,937,000",
            "QAR": "628,000",
        }
        rows = []
        for code, _flag, name, labels in CURRENCY_ROWS:
            if code == omit:
                continue
            label = labels[0]
            rows.append(
                f"<tr><td>{label}</td><td>{values[code]}</td><td>0%</td></tr>"
            )
        return "<table>" + "".join(rows) + "</table>"

    def test_parses_required_free_market_rows_and_converts_rial_to_toman(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        self.assertEqual(len(rates), 25)
        self.assertEqual(rates["USD"], Decimal("228600"))
        self.assertEqual(rates["TRY"], Decimal("4689"))
        self.assertEqual(rates["KWD"], Decimal("741400"))

    def test_missing_required_currency_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "QAR"):
            parse_tgju_currency_page(self._fixture_html(omit="QAR"))

    def test_build_post_uses_new_compact_format(self):
        rates = parse_tgju_currency_page(self._fixture_html())
        post = build_iran_fx_post(\n            rates,\n            {"USD": Decimal("1.25"), "TRY": Decimal("-0.50")},\n            {"USD": Decimal("8.75"), "TRY": Decimal("3.20")},\n        )\n        self.assertIn("نرخ ارز آزاد ایران", post)
        self.assertIn("<pre>", post)
        self.assertIn("🇺🇸 USD", post)
        self.assertIn("228,600", post)
        self.assertIn("Δ24H", post)
        self.assertIn("Δ1M", post)
        self.assertIn("+1.25%", post)
        self.assertIn("+8.75%", post)
        self.assertIn("🇹🇷 TRY", post)
        self.assertIn("4,689", post)
        self.assertIn("💵 واحد: تومان 🇮🇷", post)
        self.assertNotIn("= دلار آمریکا", post)


if __name__ == "__main__":
    unittest.main()
