import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from data_foundation.snapshot import SnapshotError, SnapshotStore, validate_snapshot


ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    def load(self):
        return json.loads((ROOT / "data_foundation" / "sample_snapshot.json").read_text(encoding="utf-8"))

    def test_sample_snapshot_validates_and_keeps_decimal_strings(self):
        result = validate_snapshot(self.load(), now=datetime(2026, 9, 25, 19, tzinfo=timezone.utc))
        self.assertEqual(result["quotes"][0]["ask"], "48.8200")
        self.assertEqual(result["quotes"][1]["quote_currency"], "TOMAN")

    def test_duplicate_ids_and_float_values_fail_closed(self):
        payload = self.load()
        payload["quotes"][1]["quote_id"] = payload["quotes"][0]["quote_id"]
        with self.assertRaises(SnapshotError):
            validate_snapshot(payload)
        payload = self.load()
        payload["quotes"][0]["ask"] = 48.82
        with self.assertRaises(SnapshotError):
            validate_snapshot(payload)

    def test_future_snapshot_and_atomic_store(self):
        payload = self.load()
        payload["collected_at"] = "2026-09-26T18:00:00Z"
        with self.assertRaises(SnapshotError):
            validate_snapshot(payload, now=datetime(2026, 9, 25, 19, tzinfo=timezone.utc))
        payload = self.load()
        with tempfile.TemporaryDirectory() as folder:
            store = SnapshotStore(Path(folder))
            path = store.write(payload)
            self.assertEqual(store.latest()["snapshot_id"], payload["snapshot_id"])
            self.assertTrue(path.exists())
            self.assertFalse((Path(folder) / f"{payload['snapshot_id']}.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()

