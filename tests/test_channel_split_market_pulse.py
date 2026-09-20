import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from bank_compare import BankQuote  # noqa: E402
from market_pulse import build_turkey_fx_pulse_post  # noqa: E402


class MarketPulseTests(unittest.TestCase):
    def test_pulse_shows_midpoint_and_24h_change(self):
        usd = [
            BankQuote("Kapalıçarşı", Decimal("48.6900"), Decimal("48.7100")),
        ]
        eur = [
            BankQuote("Kapalıçarşı", Decimal("57.1000"), Decimal("57.3000")),
        ]
        previous_usd = {
            "Kapalıçarşı": (Decimal("48.0000"), Decimal("48.2000")),
        }
        previous_eur = {
            "Kapalıçarşı": (Decimal("56.5000"), Decimal("56.7000")),
        }

        post = build_turkey_fx_pulse_post(
            usd,
            eur,
            previous_usd,
            previous_eur,
            now=datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIn("نبض بازار ارز ترکیه", post)
        self.assertIn("USD/TRY", post)
        self.assertIn("EUR/TRY", post)
        self.assertIn("48.7000", post)
        self.assertIn("57.2000", post)
        self.assertIn("+1.25%", post)
        self.assertIn("+1.06%", post)
        self.assertIn("استانبول", post)

    def test_pulse_uses_dash_without_previous_snapshot(self):
        usd = [
            BankQuote("Kapalıçarşı", Decimal("48.6900"), Decimal("48.7100")),
        ]
        eur = [
            BankQuote("Kapalıçarşı", Decimal("57.1000"), Decimal("57.3000")),
        ]

        post = build_turkey_fx_pulse_post(usd, eur)

        self.assertEqual(post.count("—"), 2)

    def test_pulse_requires_kapalicarsi(self):
        usd = [
            BankQuote("Garanti BBVA", Decimal("47.5000"), Decimal("49.5000")),
        ]
        eur = [
            BankQuote("Kapalıçarşı", Decimal("57.1000"), Decimal("57.3000")),
        ]

        with self.assertRaises(ValueError):
            build_turkey_fx_pulse_post(usd, eur)


if __name__ == "__main__":
    unittest.main()
