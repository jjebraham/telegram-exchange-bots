import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api import pricing


class TryPricingAdminTests(unittest.TestCase):
    def make_db(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "pricing.sqlite3"
        with sqlite3.connect(path) as connection:
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
        return path

    def test_admin_update_writes_same_canonical_keys(self):
        db = self.make_db()
        env = {
            "KIANI_PRICING_DB_PATH": str(db),
            "ADMIN_PANEL_USERNAME": "admin",
            "ADMIN_PANEL_PASSWORD": "secret",
        }
        request = pricing.TryPricingUpdate(
            username="admin",
            password="secret",
            buy_adjustment_pct="1.25",
            sell_adjustment_pct="-2.25",
        )

        with patch.dict(os.environ, env, clear=False), patch.object(
            pricing, "_write_admin_log"
        ):
            result = asyncio.run(pricing.admin_update_try_pricing(request))

        self.assertEqual(result["status"], "success")
        with sqlite3.connect(db) as connection:
            values = dict(
                connection.execute(
                    "SELECT key, value FROM pricing_settings"
                ).fetchall()
            )
        self.assertEqual(values["user_tl_buy_adjustment_pct"], "1.25")
        self.assertEqual(values["user_tl_sell_adjustment_pct"], "-2.25")

    def test_out_of_range_value_is_rejected(self):
        db = self.make_db()
        env = {
            "KIANI_PRICING_DB_PATH": str(db),
            "ADMIN_PANEL_USERNAME": "admin",
            "ADMIN_PANEL_PASSWORD": "secret",
        }
        request = pricing.TryPricingUpdate(
            username="admin",
            password="secret",
            buy_adjustment_pct="51",
            sell_adjustment_pct="-2",
        )

        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(pricing.admin_update_try_pricing(request))

        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
