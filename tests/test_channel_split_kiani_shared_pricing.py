import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

from kiani_shared_pricing import (  # noqa: E402
    DEFAULTS,
    calculate_kiani_rates,
    load_shared_adjustments,
)


class KianiSharedPricingTests(unittest.TestCase):
    def test_loads_all_adjustments_from_shared_admin_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pricing.sqlite3"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                [(key, str(value)) for key, value in DEFAULTS.items()],
            )
            connection.commit()
            connection.close()

            loaded = load_shared_adjustments(db)

        self.assertEqual(loaded, DEFAULTS)

    def test_missing_admin_setting_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pricing.sqlite3"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                ("user_tl_buy_adjustment_pct", "0.67"),
            )
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(RuntimeError, "missing required settings"):
                load_shared_adjustments(db)

    def test_calculation_uses_six_independent_admin_percentages(self):
        rates = calculate_kiani_rates(
            Decimal("230000"),
            Decimal("48.5"),
            dict(DEFAULTS),
        )

        self.assertEqual(rates["buy_lira"], Decimal("4.77E+3"))
        self.assertEqual(rates["sell_lira"], Decimal("4.60E+3"))
        self.assertEqual(rates["buy_usdt"], Decimal("2.323E+5"))
        self.assertEqual(rates["sell_usdt"], Decimal("2.277E+5"))
        self.assertEqual(rates["lira_to_usdt"], Decimal("49.47"))
        self.assertEqual(rates["usdt_to_lira"], Decimal("47.53"))


if __name__ == "__main__":
    unittest.main()
