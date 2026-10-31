import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from main_user_pricing_client import get_adjustment_factor
from main_user_runtime import (
    PATCH_SPECS,
    RuntimePatchError,
    source_path_from_environment,
    transform_source,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRACKED_BOT = REPOSITORY_ROOT / "main_user_bot_clone.py"


class MainUserSharedPricingTests(unittest.TestCase):
    def test_runtime_requires_an_explicit_bot_source_path(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimePatchError):
                source_path_from_environment()

        with patch.dict("os.environ", {"MAIN_USER_BOT_SOURCE": "bot.py"}):
            self.assertEqual(
                source_path_from_environment().name,
                "bot.py",
            )

    def make_db(self, values):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = str(Path(temp_dir.name) / "pricing.db")
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                "CREATE TABLE pricing_settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            connection.executemany(
                "INSERT INTO pricing_settings (key, value) VALUES (?, ?)",
                values.items(),
            )
            connection.commit()
        finally:
            connection.close()
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

    def test_tracked_clone_patches_and_compiles(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        patched, names = transform_source(source)

        self.assertEqual(set(names), set(PATCH_SPECS))
        self.assertIn("_pricing_factor", patched)
        self.assertIn('_canonical_try_rate("buy_lira")', patched)
        self.assertIn('_canonical_try_rate("sell_lira")', patched)
        self.assertIn("user_usdt_buy_adjustment_pct", patched)
        self.assertIn("user_usdt_to_try_adjustment_pct", patched)
        compile(patched, str(TRACKED_BOT), "exec")

    def test_lira_handlers_fail_closed_if_canonical_patch_target_drifts(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        drifted = source.replace(
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.0167)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.02)",
            1,
        )
        with self.assertRaises(RuntimePatchError):
            transform_source(drifted)

    def test_source_drift_fails_closed(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        drifted = source.replace(
            "rate = usdt_try * 1.02",
            "rate = usdt_try * 1.03",
            1,
        )
        with self.assertRaises(RuntimePatchError):
            transform_source(drifted)


if __name__ == "__main__":
    unittest.main()

