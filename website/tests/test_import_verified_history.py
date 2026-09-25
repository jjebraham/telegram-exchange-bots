"""Regression test for verified digest unit mapping and cursor backfill."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from api import store
from api.import_verified_history import collect_hawala_snapshot, collect_new_snapshots, main
from data_foundation.snapshot import SnapshotError


class DigestImportTests(unittest.TestCase):
    def test_digest_rows_are_mapped_and_backfilled_after_old_cursor(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source = root / "publisher.sqlite3"
            website = root / "website.sqlite3"
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with sqlite3.connect(source) as db:
                db.execute(
                    """CREATE TABLE published_value_snapshots (
                        id INTEGER PRIMARY KEY, recorded_at_utc TEXT NOT NULL,
                        board TEXT NOT NULL, item TEXT NOT NULL, value TEXT NOT NULL
                    )"""
                )
                db.executemany(
                    "INSERT INTO published_value_snapshots VALUES (?, ?, 'daily-digest', ?, ?)",
                    [
                        (1, stamp, "USD", "235000"),
                        (2, stamp, "BTC", "84455.1"),
                        (3, stamp, "COIN_EMAMI", "240005000"),
                        (4, stamp, "XAUUSD", "4308.11"),
                        (5, stamp, "IQD100", "15020"),
                        (6, stamp, "UNKNOWN", "100"),
                    ],
                )
            with patch.dict(os.environ, {"ALANCHANDE_DB_PATH": str(website)}):
                # Simulate Phase 3 having advanced the old shared cursor
                # beyond digest rows before the new digest cursor existed.
                store.ingest_snapshots([], cursors={"published_value_snapshots": 100})
                snapshots, cursors = collect_new_snapshots(source)
                self.assertEqual(len(snapshots), 1)
                quotes = {q["base_asset"]: q for q in snapshots[0]["quotes"]}
                self.assertEqual(len(quotes), 5)
                self.assertEqual(quotes["BTC"]["quote_currency"], "USD")
                self.assertEqual(quotes["BTC"]["reference"], "84455.1")
                self.assertEqual(quotes["XAU"]["unit"], "troy-ounce")
                self.assertEqual(quotes["IQD"]["base_quantity"], "100")
                self.assertEqual(quotes["USD"]["quote_currency"], "TOMAN")
                self.assertEqual(cursors["published_value_snapshots_daily_digest"], 6)
                store.ingest_snapshots(snapshots, cursors=cursors)
                remaining, _ = collect_new_snapshots(source)
                self.assertEqual(remaining, [])
                self.assertEqual(len(store.latest_quotes()), 5)

    def test_hawala_export_requires_fresh_successful_telegram_snapshot(self) -> None:
        from datetime import timedelta

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "hawala.json"
            now = datetime.now(timezone.utc)
            rates = {code: 5000 for code in ("USD", "EUR", "GBP", "CAD", "AUD", "SEK", "TRY")}
            payload = {
                "source": "kiani-hawala",
                "generated_at": now.isoformat(),
                "rates": rates,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = collect_hawala_snapshot(path, now=now)
            self.assertEqual(len(snapshot["quotes"]), 7)
            self.assertEqual(snapshot["quotes"][0]["quote_kind"], "customer_rate")
            self.assertEqual(snapshot["quotes"][0]["reference"], "5000")
            payload["generated_at"] = (now - timedelta(minutes=16)).isoformat()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SnapshotError):
                collect_hawala_snapshot(path, now=now)

    def test_stale_optional_hawala_does_not_block_other_imports(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            source, website, hawala = (root / name for name in (
                "publisher.sqlite3", "website.sqlite3", "hawala.json",
            ))
            with sqlite3.connect(source) as db:
                db.execute(
                    """CREATE TABLE published_value_snapshots (
                        id INTEGER PRIMARY KEY, recorded_at_utc TEXT,
                        board TEXT, item TEXT, value TEXT
                    )"""
                )
                db.execute(
                    "INSERT INTO published_value_snapshots VALUES (1, ?, 'iran-fx', 'USD', '235000')",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
                )
            hawala.write_text(json.dumps({
                "source": "kiani-hawala", "generated_at": "2020-01-01T00:00:00+00:00",
                "rates": {code: 5000 for code in ("USD", "EUR", "GBP", "CAD", "AUD", "SEK", "TRY")},
            }), encoding="utf-8")
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {
                "ALANCHANDE_DB_PATH": str(website),
                "ALANCHANDE_SOURCE_DB": str(source),
                "ALANCHANDE_HAWALA_SNAPSHOT": str(hawala),
            }), patch("sys.argv", ["import_verified_history"]), redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main(), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["quotes"], 1)
            self.assertTrue(summary["hawala"].startswith("skipped:"))
            self.assertIn("HAWALA SKIPPED", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
