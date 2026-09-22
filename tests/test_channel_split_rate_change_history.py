import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from rate_change_history import (  # noqa: E402
    load_published_values_near_age,
    percentage_changes,
    record_published_values,
)


class RateChangeHistoryTests(unittest.TestCase):
    def test_loads_batch_closest_to_24h(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
            record_published_values(
                db,
                "usdt-buy",
                {"Wallex": Decimal("200000")},
                now=now - timedelta(hours=23),
            )
            record_published_values(
                db,
                "usdt-buy",
                {"Wallex": Decimal("190000")},
                now=now - timedelta(hours=29),
            )

            loaded = load_published_values_near_age(
                db,
                "usdt-buy",
                target_hours=24,
                min_age_hours=18,
                max_age_hours=30,
                now=now,
            )
            self.assertEqual(loaded["Wallex"], Decimal("200000"))

    def test_loads_batch_closest_to_30_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
            record_published_values(
                db,
                "iran-fx",
                {"USD": Decimal("180000")},
                now=now - timedelta(days=30, hours=2),
            )

            loaded = load_published_values_near_age(
                db,
                "iran-fx",
                target_hours=24 * 30,
                min_age_hours=24 * 25,
                max_age_hours=24 * 35,
                now=now,
            )
            self.assertEqual(loaded["USD"], Decimal("180000"))

    def test_percentage_changes_only_uses_matching_positive_baselines(self):
        changes = percentage_changes(
            {"USD": Decimal("220000"), "EUR": Decimal("250000")},
            {"USD": Decimal("200000")},
        )
        self.assertEqual(changes["USD"], Decimal("10"))
        self.assertNotIn("EUR", changes)


if __name__ == "__main__":
    unittest.main()
