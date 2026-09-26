"""Regression tests for daily Kiani -> AlanChande Telegram forwarding."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from channel_split.telegram_forwarding import (
    already_forwarded,
    find_source_for_slot,
    forward_daily_slot,
    record_forward,
    record_source_message,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "channel_split" / "publish_channels.py"
LAUNCHER = ROOT / "channel_split" / "run_channel_split_production.sh"
TRY_TIMER = (
    ROOT / "deploy" / "systemd" / "channel-split-prod-forward-kiani-try.timer"
)
RATES_TIMER = (
    ROOT / "deploy" / "systemd" / "channel-split-prod-forward-kiani-rates.timer"
)


class KianiForwardStateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tmpdir.name) / "forward.sqlite3"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_selects_1140_try_source_and_not_other_hour(self):
        # 08:40 UTC = 11:40 Europe/Istanbul.
        record_source_message(
            self.db,
            source_key="kiani-try",
            message_id=1001,
            source_chat_id="@ExchangeKiani",
            sent_at=datetime(2026, 9, 26, 8, 40, 12, tzinfo=timezone.utc),
        )
        record_source_message(
            self.db,
            source_key="kiani-try",
            message_id=1002,
            source_chat_id="@ExchangeKiani",
            sent_at=datetime(2026, 9, 26, 9, 40, 10, tzinfo=timezone.utc),
        )

        selected = find_source_for_slot(
            self.db,
            source_key="kiani-try",
            local_date="2026-09-26",
            expected_local_time="11:40",
            tolerance_minutes=12,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.message_id, 1001)

    def test_selects_1210_combined_rates_source(self):
        # 09:10 UTC = 12:10 Europe/Istanbul.
        record_source_message(
            self.db,
            source_key="kiani-rates",
            message_id=2001,
            source_chat_id="@ExchangeKiani",
            sent_at=datetime(2026, 9, 26, 9, 10, 5, tzinfo=timezone.utc),
        )

        selected = find_source_for_slot(
            self.db,
            source_key="kiani-rates",
            local_date="2026-09-26",
            expected_local_time="12:10",
            tolerance_minutes=12,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.message_id, 2001)

    def test_does_not_forward_wrong_hour_when_target_source_is_missing(self):
        record_source_message(
            self.db,
            source_key="kiani-try",
            message_id=3001,
            source_chat_id="@ExchangeKiani",
            sent_at=datetime(2026, 9, 26, 7, 40, tzinfo=timezone.utc),
        )

        selected = find_source_for_slot(
            self.db,
            source_key="kiani-try",
            local_date="2026-09-26",
            expected_local_time="11:40",
            tolerance_minutes=12,
        )
        self.assertIsNone(selected)

    def test_forward_delivery_is_idempotent_per_day_and_source_type(self):
        self.assertFalse(
            already_forwarded(
                self.db,
                source_key="kiani-try",
                local_date="2026-09-26",
            )
        )
        record_forward(
            self.db,
            source_key="kiani-try",
            local_date="2026-09-26",
            source_message_id=4001,
            forwarded_message_id=5001,
            forwarded_at=datetime(2026, 9, 26, 8, 42, tzinfo=timezone.utc),
        )
        self.assertTrue(
            already_forwarded(
                self.db,
                source_key="kiani-try",
                local_date="2026-09-26",
            )
        )

    def test_dry_run_finds_exact_source_without_recording_delivery(self):
        record_source_message(
            self.db,
            source_key="kiani-rates",
            message_id=6001,
            source_chat_id="@ExchangeKiani",
            sent_at=datetime(2026, 9, 26, 9, 10, tzinfo=timezone.utc),
        )
        outcome = forward_daily_slot(
            self.db,
            source_key="kiani-rates",
            expected_local_time="12:10",
            token="unused-in-dry-run",
            source_chat_id="@ExchangeKiani",
            destination_chat_id="@alanchande_com",
            now=datetime(2026, 9, 26, 9, 12, tzinfo=timezone.utc),
            dry_run=True,
        )
        self.assertEqual(outcome.status, "dry-run-ready")
        self.assertEqual(outcome.source_message_id, 6001)
        self.assertFalse(
            already_forwarded(
                self.db,
                source_key="kiani-rates",
                local_date="2026-09-26",
            )
        )


class KianiForwardProductionWiringTests(unittest.TestCase):
    def test_publisher_records_source_message_ids_for_target_post_types(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn('add_kiani(build_kiani_rate_post(get_rates()), "kiani-rates")', text)
        self.assertIn('"kiani-try"', text)
        self.assertIn("record_source_message(", text)
        self.assertIn('destination_env == "KIANI_CHANNEL_ID"', text)

    def test_launcher_allows_both_forward_jobs(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("forward-kiani-try", text)
        self.assertIn("forward-kiani-rates", text)

    def test_try_forward_timer_runs_after_1140_istanbul_source_post(self):
        text = TRY_TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 11:42:00 Europe/Istanbul", text)
        self.assertIn("Persistent=false", text)
        self.assertIn(
            "Unit=channel-split-production@forward-kiani-try.service",
            text,
        )

    def test_rates_forward_timer_runs_after_1210_istanbul_source_post(self):
        text = RATES_TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 12:12:00 Europe/Istanbul", text)
        self.assertIn("Persistent=false", text)
        self.assertIn(
            "Unit=channel-split-production@forward-kiani-rates.service",
            text,
        )


if __name__ == "__main__":
    unittest.main()
