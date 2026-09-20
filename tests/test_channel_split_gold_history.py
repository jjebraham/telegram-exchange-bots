import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from gold_history import load_turkey_gold_near_24h, record_turkey_gold_quotes  # noqa: E402
from gold_prices import GoldQuote  # noqa: E402


class TurkeyGoldHistoryTests(unittest.TestCase):
    def test_loads_snapshot_closest_to_24h(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        old_quotes = [
            GoldQuote("gram", "گرم طلا", "x", Decimal("6800"), Decimal("6810")),
            GoldQuote("tam", "تمام سکه", "x", Decimal("44000"), Decimal("44500")),
        ]
        recent_quotes = [
            GoldQuote("gram", "گرم طلا", "x", Decimal("7000"), Decimal("7010")),
            GoldQuote("tam", "تمام سکه", "x", Decimal("45000"), Decimal("45500")),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"
            record_turkey_gold_quotes(
                db,
                old_quotes,
                now=now - timedelta(hours=24),
            )
            record_turkey_gold_quotes(
                db,
                recent_quotes,
                now=now - timedelta(hours=3),
            )
            previous = load_turkey_gold_near_24h(db, now=now)

        self.assertEqual(
            previous["gram"],
            (Decimal("6800"), Decimal("6810")),
        )
        self.assertEqual(
            previous["tam"],
            (Decimal("44000"), Decimal("44500")),
        )

    def test_returns_empty_without_18_to_30_hour_snapshot(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        quotes = [
            GoldQuote("gram", "گرم طلا", "x", Decimal("6800"), Decimal("6810")),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"
            record_turkey_gold_quotes(
                db,
                quotes,
                now=now - timedelta(hours=5),
            )
            previous = load_turkey_gold_near_24h(db, now=now)

        self.assertEqual(previous, {})


if __name__ == "__main__":
    unittest.main()
