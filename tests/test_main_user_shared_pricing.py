import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from main_user_pricing_client import get_adjustment_factor
from main_user_runtime import PATCH_SPECS, RuntimePatchError, transform_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRACKED_BOT = REPOSITORY_ROOT / "main_user_bot_clone.py"


class MainUserSharedPricingTests(unittest.TestCase):
    def make_db(self, values):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = str(Path(temp_dir.name) / "pricing.db")
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            connection.executemany(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                values.items(),
            )
        return db_path

    def test_client_reads_factor_and_falls_back(self):
        db_path = self.make_db({"user_tl_buy_adjustment_pct": "2.75"})
        self.assertEqual(
            get_adjustment_factor(
                "user_tl_buy_adjustment_pct", "2", db_path
            ),
            Decimal("1.0275"),
        )
        self.assertEqual(
            get_adjustment_factor("missing", "-3", db_path),
            Decimal("0.97"),
        )

    def test_tracked_clone_patches_only_try_handlers_and_compiles(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        patched, names = transform_source(source)

        self.assertEqual(set(names), set(PATCH_SPECS))
        self.assertEqual(len(names), 4)
        self.assertIn('_canonical_try_rate("buy_lira")', patched)
        self.assertIn('_canonical_try_rate("sell_lira")', patched)
        self.assertIn("rate = round_to_nearest_10(eff_toman * 1.01)", patched)
        self.assertIn("rate = usdt_try * 1.02", patched)
        compile(patched, str(TRACKED_BOT), "exec")

    def test_source_drift_fails_closed(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        drifted = source.replace(
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.0167)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.02)",
            1,
        )
        with self.assertRaises(RuntimePatchError):
            transform_source(drifted)


if __name__ == "__main__":
    unittest.main()
