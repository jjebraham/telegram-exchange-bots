import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from iran_gold import IranGoldMarket  # noqa: E402
from iran_gold_history import load_iran_gold_near_24h, record_iran_gold_market  # noqa: E402


class IranGoldHistoryTests(unittest.TestCase):
    def test_loads_snapshot_closest_to_24h(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

        old = IranGoldMarket(
            coin_prices_rial={
                "سکه امامی": Decimal("2300000000"),
                "سکه بهار آزادی": Decimal("2250000000"),
                "نیم سکه": Decimal("1150000000"),
                "ربع سکه": Decimal("600000000"),
                "سکه گرمی": Decimal("300000000"),
            },
            bubble_values_rial={},
            gold18_rial=Decimal("230000000"),
            mesghal_rial=Decimal("990000000"),
        )
        recent = IranGoldMarket(
            coin_prices_rial={
                "سکه امامی": Decimal("2400000000"),
                "سکه بهار آزادی": Decimal("2350000000"),
                "نیم سکه": Decimal("1200000000"),
                "ربع سکه": Decimal("650000000"),
                "سکه گرمی": Decimal("330000000"),
            },
            bubble_values_rial={},
            gold18_rial=Decimal("240000000"),
            mesghal_rial=Decimal("1030000000"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"
            record_iran_gold_market(
                db,
                old,
                now=now - timedelta(hours=24),
            )
            record_iran_gold_market(
                db,
                recent,
                now=now - timedelta(hours=3),
            )
            previous = load_iran_gold_near_24h(db, now=now)

        self.assertEqual(previous["سکه امامی"], Decimal("2300000000"))
        self.assertEqual(previous["طلای ۱۸ عیار"], Decimal("230000000"))
        self.assertEqual(previous["مثقال طلا"], Decimal("990000000"))

    def test_returns_empty_without_18_to_30_hour_snapshot(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        market = IranGoldMarket(
            coin_prices_rial={
                "سکه امامی": Decimal("2300000000"),
            },
            bubble_values_rial={},
        )

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "market.sqlite3"
            record_iran_gold_market(
                db,
                market,
                now=now - timedelta(hours=4),
            )
            previous = load_iran_gold_near_24h(db, now=now)

        self.assertEqual(previous, {})


if __name__ == "__main__":
    unittest.main()
