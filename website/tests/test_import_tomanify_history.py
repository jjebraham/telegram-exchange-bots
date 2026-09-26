"""Tests for archived Tomanify feed import and separate source history."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api import store
from api.import_tomanify_history import build_snapshot, collect_new_snapshots
from data_foundation.snapshot import SnapshotError


def feed(date_text: str | None = None) -> dict:
    return {
        "generated_by_tomanify_at": date_text or datetime.now(timezone.utc).date().isoformat(),
        "values": {"USD": 235200, "EUR": "267910.5", "AED": 64073, "TRY": 4907, "CNY": 35250},
    }


class TomanifyHistoryTests(unittest.TestCase):
    def test_snapshot_maps_supported_currencies_to_a_separate_source_series(self) -> None:
        now = datetime.now(timezone.utc)
        sha = "a" * 40
        snapshot = build_snapshot(feed(), sha, (now - timedelta(minutes=2)).isoformat(), now=now)
        quotes = {quote["base_asset"]: quote for quote in snapshot["quotes"]}

        self.assertEqual(snapshot["snapshot_id"], f"tomanify-{sha}")
        self.assertEqual(set(quotes), {"USD", "EUR", "AED", "TRY", "CNY"})
        self.assertEqual(quotes["USD"]["series_id"], "fx:usd:iran-open:toman:tomanify:v1")
        self.assertEqual(quotes["USD"]["source_id"], "tomanify:rate-json-default")
        self.assertEqual(quotes["USD"]["verification_status"], "source_published")
        self.assertEqual(quotes["USD"]["reference"], "235200")
        self.assertIsNone(quotes["USD"]["source_observed_at"])
        self.assertEqual(quotes["USD"]["source_reported_date"], feed()["generated_by_tomanify_at"])
        self.assertEqual(quotes["USD"]["methodology_version"], "tomanify-github-archive-commit-time-v1")

    def test_legacy_generated_timestamp_maps_only_its_calendar_date(self) -> None:
        now = datetime.now(timezone.utc)
        sha = "9" * 40
        archived = feed()
        del archived["generated_by_tomanify_at"]
        archived["generated_at"] = "2025-10-06 18:04:28"
        snapshot = build_snapshot(
            archived, sha, (now - timedelta(minutes=2)).isoformat(), now=now
        )
        quote = next(q for q in snapshot["quotes"] if q["base_asset"] == "USD")
        self.assertEqual(quote["source_reported_date"], "2025-10-06")
        self.assertIsNone(quote["source_observed_at"])

    def test_invalid_feed_date_rate_and_commit_hash_are_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        stamp = (now - timedelta(minutes=2)).isoformat()
        with self.assertRaises(SnapshotError):
            build_snapshot(feed("not-a-date"), "a" * 40, stamp, now=now)
        legacy_invalid = feed()
        del legacy_invalid["generated_by_tomanify_at"]
        legacy_invalid["generated_at"] = "2025-10-06 25:04:28"
        with self.assertRaises(SnapshotError):
            build_snapshot(legacy_invalid, "a" * 40, stamp, now=now)
        broken = feed()
        broken["values"]["USD"] = -1
        with self.assertRaises(SnapshotError):
            build_snapshot(broken, "a" * 40, stamp, now=now)
        missing_usd = feed()
        del missing_usd["values"]["USD"]
        partial = build_snapshot(missing_usd, "f" * 40, stamp, now=now)
        self.assertNotIn("USD", {quote["base_asset"] for quote in partial["quotes"]})
        unsupported = feed()
        unsupported["values"] = {"UNKNOWN": 1}
        with self.assertRaises(SnapshotError):
            build_snapshot(unsupported, "1" * 40, stamp, now=now)
        with self.assertRaises(SnapshotError):
            build_snapshot(feed(), "not-a-commit", stamp, now=now)
        old_date = (date.today() - timedelta(days=2)).isoformat()
        stale = build_snapshot(feed(old_date), "e" * 40, stamp, now=now)
        self.assertLessEqual(datetime.fromisoformat(stale["quotes"][0]["valid_until"]), now)

    def test_github_archive_snapshots_are_imported_in_chronological_order(self) -> None:
        now = datetime.now(timezone.utc)
        older_sha, newer_sha = "b" * 40, "c" * 40
        commits = [
            {"sha": newer_sha, "commit": {"committer": {"date": (now - timedelta(minutes=1)).isoformat()}}},
            {"sha": older_sha, "commit": {"committer": {"date": (now - timedelta(minutes=2)).isoformat()}}},
        ]

        def fetch(url: str) -> object:
            if "api.github.com" in url:
                return commits
            if older_sha in url:
                return feed()
            if newer_sha in url:
                return feed()
            raise AssertionError(f"unexpected URL {url}")

        with patch("api.import_tomanify_history._fetch_json", side_effect=fetch):
            snapshots, scan = collect_new_snapshots(limit=10)
        self.assertEqual([snapshot["snapshot_id"] for snapshot in snapshots],
                         [f"tomanify-{older_sha}", f"tomanify-{newer_sha}"])
        self.assertEqual(scan["commit_count"], 2)
        self.assertFalse(scan["stopped_at_existing_snapshot"])

    def test_source_published_series_are_queryable_without_replacing_verified_series(self) -> None:
        now = datetime.now(timezone.utc)
        stamp = (now - timedelta(minutes=2)).isoformat()
        source = build_snapshot(feed(), "d" * 40, stamp, now=now)
        verified = {
            "schema_version": "1", "snapshot_id": "existing-verified", "collected_at": stamp,
            "quotes": [{
                "quote_id": "verified-usd", "series_id": "fx:usd:iran-open:toman:reference:v1",
                "instrument_id": "fx:usd", "base_asset": "USD", "base_quantity": "1",
                "quote_currency": "TOMAN", "unit": "currency-unit", "quote_kind": "market_reference",
                "bid": None, "ask": None, "reference": "234900", "mid": None,
                "source_id": "publisher:telegram", "source_family": "telegram_verified_history",
                "source_observed_at": None, "collected_at": stamp, "verification_status": "verified",
                "category": "iran_fx", "display_name_fa": "USD · دلار آمریکا",
            }],
        }
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            database = Path(temporary) / "market.sqlite3"
            with patch.dict(os.environ, {"ALANCHANDE_DB_PATH": str(database)}):
                store.ingest_snapshots([verified, source])
                latest = store.latest_quotes(now=now + timedelta(minutes=1))
                source_quote = next(q for q in latest if q["source_id"] == "tomanify:rate-json-default")
                self.assertEqual(source_quote["freshness_status"], "fresh")
                self.assertEqual(source_quote["source_reported_date"], feed()["generated_by_tomanify_at"])
                history = store.history(
                    "fx:usd:iran-open:toman:tomanify:v1", now - timedelta(hours=1),
                    now + timedelta(hours=1), 100,
                )
                self.assertEqual(history["sampling_kind"], "published_source_observations")
                self.assertEqual(history["returned_point_count"], 1)
                self.assertEqual(history["points"][0]["quote"]["verification_status"], "source_published")
                verified_quote = next(q for q in latest if q["series_id"] == "fx:usd:iran-open:toman:reference:v1")
                self.assertEqual(verified_quote["verification_status"], "verified")


if __name__ == "__main__":
    unittest.main()
