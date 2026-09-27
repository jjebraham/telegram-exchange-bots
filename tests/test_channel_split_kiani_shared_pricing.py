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
    calculate_hawala_try_rate,
    calculate_kiani_rates,
    calculate_kiani_try_rates,
    load_hawala_try_adjustment,
    load_shared_adjustments,
    load_try_adjustments,
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


    def test_try_only_loader_and_calculation_match_full_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pricing.sqlite3"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                [
                    ("user_tl_buy_adjustment_pct", "1"),
                    ("user_tl_sell_adjustment_pct", "-2"),
                ],
            )
            connection.commit()
            connection.close()

            adjustments = load_try_adjustments(db)

        try_only = calculate_kiani_try_rates(
            Decimal("237580"),
            Decimal("49.40"),
            adjustments,
        )
        full_adjustments = dict(DEFAULTS)
        full_adjustments.update(adjustments)
        full = calculate_kiani_rates(
            Decimal("237580"),
            Decimal("49.40"),
            full_adjustments,
        )

        self.assertEqual(try_only["buy_lira"], full["buy_lira"])
        self.assertEqual(try_only["sell_lira"], full["sell_lira"])
        self.assertEqual(try_only["buy_lira"] % Decimal("10"), Decimal("0"))
        self.assertEqual(try_only["sell_lira"] % Decimal("10"), Decimal("0"))



    def test_hawala_try_uses_same_base_and_rounding_as_sell_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pricing.sqlite3"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                [
                    ("user_tl_buy_adjustment_pct", "1"),
                    ("user_tl_sell_adjustment_pct", "-2"),
                    ("hawala_try_adjustment_pct", "-2"),
                ],
            )
            connection.commit()
            connection.close()

            try_adjustments = load_try_adjustments(db)
            hawala_adjustment = load_hawala_try_adjustment(db)

        market_usdt_toman = Decimal("235656")
        market_usdt_try = Decimal("48.947")

        try_rates = calculate_kiani_try_rates(
            market_usdt_toman,
            market_usdt_try,
            try_adjustments,
        )
        hawala_rate = calculate_hawala_try_rate(
            market_usdt_toman,
            market_usdt_try,
            hawala_adjustment,
        )

        self.assertEqual(hawala_adjustment, Decimal("-2"))
        self.assertEqual(hawala_rate, try_rates["sell_lira"])
        self.assertEqual(hawala_rate % Decimal("10"), Decimal("0"))

    def test_hawala_try_setting_remains_independent(self):
        base_toman = Decimal("235656")
        usdt_try = Decimal("48.947")

        sell_rate = calculate_hawala_try_rate(
            base_toman,
            usdt_try,
            Decimal("-2"),
        )
        hawala_rate = calculate_hawala_try_rate(
            base_toman,
            usdt_try,
            Decimal("-3"),
        )

        self.assertNotEqual(hawala_rate, sell_rate)



if __name__ == "__main__":
    unittest.main()
