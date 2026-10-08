import ast
import io
import json
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from main_user_pricing_client import get_adjustment_factor, get_canonical_try_rate
from main_user_runtime import (
    BUY_CANONICAL_BLOCK,
    BUY_LEGACY_BLOCK,
    PATCH_SPECS,
    SELL_CANONICAL_BLOCK,
    SELL_LEGACY_BLOCK,
    RuntimePatchError,
    transform_source,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRACKED_BOT = REPOSITORY_ROOT / "main_user_bot_clone.py"
CANONICAL_RATES = {
    "rates": {
        "buy_lira": 5450,
        "sell_lira": 5240,
        "buy_adjustment_pct": "2",
        "sell_adjustment_pct": "-2",
        "market_usdt_toman": "262922.5",
        "market_usdt_try": "49.182",
        "source": "kiani-price-cache",
    }
}


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

    def canonical_db(self, buy="2", sell="-2"):
        return self.make_db({
            "user_tl_buy_adjustment_pct": buy,
            "user_tl_sell_adjustment_pct": sell,
        })

    def fetch_payload(self, payload=None):
        return io.BytesIO(json.dumps(payload or CANONICAL_RATES).encode("utf-8"))

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

    def test_canonical_buy_and_sell_match_shared_admin_percentages(self):
        db_path = self.canonical_db()
        with patch(
            "main_user_pricing_client.urlopen",
            side_effect=lambda request, timeout: self.fetch_payload(),
        ):
            self.assertEqual(
                get_canonical_try_rate("buy_lira", url="http://rates.test/try", db_path=db_path),
                5450,
            )
            self.assertEqual(
                get_canonical_try_rate("sell_lira", url="http://rates.test/try", db_path=db_path),
                5240,
            )

    def test_canonical_client_uses_same_database_environment_as_api(self):
        db_path = self.canonical_db()
        with patch.dict(os.environ, {"KIANI_PRICING_DB_PATH": db_path}, clear=True):
            with patch(
                "main_user_pricing_client.urlopen",
                side_effect=lambda request, timeout: self.fetch_payload(),
            ):
                self.assertEqual(
                    get_canonical_try_rate("buy_lira", url="http://rates.test/try"),
                    5450,
                )

    def test_canonical_client_rejects_percentage_drift(self):
        db_path = self.canonical_db(buy="3")
        with patch(
            "main_user_pricing_client.urlopen",
            side_effect=lambda request, timeout: self.fetch_payload(),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not match the admin-panel"):
                get_canonical_try_rate(
                    "buy_lira", url="http://rates.test/try", db_path=db_path
                )

    def test_canonical_client_rejects_rate_calculation_drift(self):
        db_path = self.canonical_db()
        changed = json.loads(json.dumps(CANONICAL_RATES))
        changed["rates"]["buy_lira"] = 5400
        with patch(
            "main_user_pricing_client.urlopen",
            side_effect=lambda request, timeout: self.fetch_payload(changed),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not match its market"):
                get_canonical_try_rate(
                    "buy_lira", url="http://rates.test/try", db_path=db_path
                )

    def test_all_tracked_try_button_handlers_use_canonical_rates(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        lines = source.splitlines()
        expected = {
            "buy_lira_user": '_canonical_try_rate("buy_lira")',
            "main_menu_buy_lira_rate": '_canonical_try_rate("buy_lira")',
            "sell_lira_user": '_canonical_try_rate("sell_lira")',
            "main_menu_sell_lira_rate": '_canonical_try_rate("sell_lira")',
        }
        for function_name, call in expected.items():
            with self.subTest(handler=function_name):
                node = functions[function_name]
                block = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                self.assertIn(call, block)
                self.assertNotIn("price_cache.get_usdt_irr", block)
                self.assertNotIn("1.0167", block)
                self.assertNotIn("* 0.97", block)
        compile(source, str(TRACKED_BOT), "exec")

    def test_runtime_patcher_upgrades_legacy_source_and_is_idempotent(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        self.assertEqual(source.count(BUY_CANONICAL_BLOCK), 2)
        self.assertEqual(source.count(SELL_CANONICAL_BLOCK), 2)
        legacy = source.replace(BUY_CANONICAL_BLOCK, BUY_LEGACY_BLOCK)
        legacy = legacy.replace(SELL_CANONICAL_BLOCK, SELL_LEGACY_BLOCK)

        patched, names = transform_source(legacy)
        self.assertEqual(set(names), set(PATCH_SPECS))
        self.assertEqual(len(names), 4)
        self.assertEqual(patched, source)
        self.assertEqual(patched.count("async def _canonical_try_rate("), 1)
        self.assertIn("rate = round_to_nearest_10(eff_toman * 1.01)", patched)
        self.assertIn("rate = usdt_try * 1.02", patched)
        compile(patched, str(TRACKED_BOT), "exec")

    def test_source_drift_fails_closed(self):
        source = TRACKED_BOT.read_text(encoding="utf-8")
        drifted = source.replace(
            'rate = await _canonical_try_rate("buy_lira")',
            'rate = await _canonical_try_rate("sell_lira")',
            1,
        )
        with self.assertRaises(RuntimePatchError):
            transform_source(drifted)


if __name__ == "__main__":
    unittest.main()
