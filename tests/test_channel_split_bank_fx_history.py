import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from bank_compare import BankQuote  # noqa: E402
from market_history import load_bank_fx_near_24h, record_bank_fx_quotes  # noqa: E402


class BankFxHistoryTests(unittest.TestCase):
    def test_loads_snapshot_closest_to_24h_and_ignores_recent_one(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

        old_quotes = [
            BankQuote("Kapalıçarşı", Decimal("48.10"), Decimal("48.20")),
            BankQuote("Garanti BBVA", Decimal("47.80"), Decimal("49.10")),
        ]
        recent_quotes = [
            BankQuote("Kapalıçarşı", Decimal("48.90"), Decimal("49.00")),
            BankQuote("Garanti BBVA", Decimal("48.20"), Decimal("49.40")),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"

            record_bank_fx_quotes(
                db,
                "USD/TRY",
                old_quotes,
                now=now - timedelta(hours=24),
            )
            record_bank_fx_quotes(
                db,
                "USD/TRY",
                recent_quotes,
                now=now - timedelta(hours=2),
            )

            previous = load_bank_fx_near_24h(
                db,
                "USD/TRY",
                now=now,
            )

        self.assertEqual(
            previous["Kapalıçarşı"],
            (Decimal("48.10"), Decimal("48.20")),
        )
        self.assertEqual(
            previous["Garanti BBVA"],
            (Decimal("47.80"), Decimal("49.10")),
        )

    def test_returns_empty_when_no_snapshot_is_near_24h(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        quotes = [
            BankQuote("Kapalıçarşı", Decimal("48.10"), Decimal("48.20")),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"
            record_bank_fx_quotes(
                db,
                "USD/TRY",
                quotes,
                now=now - timedelta(hours=4),
            )
            previous = load_bank_fx_near_24h(
                db,
                "USD/TRY",
                now=now,
            )

        self.assertEqual(previous, {})


if __name__ == "__main__":
    unittest.main()
