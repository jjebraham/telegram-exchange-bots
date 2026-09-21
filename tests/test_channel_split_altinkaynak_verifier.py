import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from altinkaynak_verifier import (  # noqa: E402
    parse_currency_rows,
    parse_gold_rows,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")


class AltinkaynakVerifierTests(unittest.TestCase):
    def test_currency_rows_parse_midpoints_and_freshness(self):
        rows = [
            {
                "Alis": "48,570",
                "Satis": "48,930",
                "Kod": "USD",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
            {
                "Alis": "55,580",
                "Satis": "56,120",
                "Kod": "EUR",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
        ]

        result = parse_currency_rows(
            rows,
            now=datetime(2026, 9, 22, 12, 20, tzinfo=ISTANBUL),
        )

        self.assertEqual(result["USD/TRY"], Decimal("48.750"))
        self.assertEqual(result["EUR/TRY"], Decimal("55.850"))

    def test_gold_rows_parse_physical_products(self):
        rows = [
            {
                "Alis": "6.707,05",
                "Satis": "6.865,00",
                "Kod": "PGA",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
            {
                "Alis": "10.789,71",
                "Satis": "11.465,00",
                "Kod": "PC",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
            {
                "Alis": "21.577,25",
                "Satis": "22.925,00",
                "Kod": "PY",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
            {
                "Alis": "43.115,55",
                "Satis": "45.845,00",
                "Kod": "PT",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
        ]

        result = parse_gold_rows(
            rows,
            now=datetime(2026, 9, 22, 12, 20, tzinfo=ISTANBUL),
        )

        self.assertEqual(result["gram"], Decimal("6786.025"))
        self.assertEqual(result["quarter"], Decimal("11127.355"))
        self.assertEqual(result["half"], Decimal("22251.125"))
        self.assertEqual(result["tam"], Decimal("44480.275"))

    def test_stale_rows_fail_closed(self):
        rows = [
            {
                "Alis": "48,570",
                "Satis": "48,930",
                "Kod": "USD",
                "GuncellenmeZamani": "22.09.2026 08:00:00",
            },
            {
                "Alis": "55,580",
                "Satis": "56,120",
                "Kod": "EUR",
                "GuncellenmeZamani": "22.09.2026 08:00:00",
            },
        ]

        with self.assertRaisesRegex(ValueError, "stale"):
            parse_currency_rows(
                rows,
                now=datetime(2026, 9, 22, 12, 0, tzinfo=ISTANBUL),
                max_age_minutes=90,
            )

    def test_missing_gold_product_fails_closed(self):
        rows = [
            {
                "Alis": "6.707,05",
                "Satis": "6.865,00",
                "Kod": "PGA",
                "GuncellenmeZamani": "22.09.2026 12:00:00",
            },
        ]

        with self.assertRaisesRegex(ValueError, "missing quarter"):
            parse_gold_rows(
                rows,
                now=datetime(2026, 9, 22, 12, 20, tzinfo=ISTANBUL),
            )


if __name__ == "__main__":
    unittest.main()
