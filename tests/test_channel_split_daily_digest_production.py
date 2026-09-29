"""Regression checks for AlanChande daily-digest production wiring."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "channel_split" / "publish_channels.py"
LAUNCHER = ROOT / "channel_split" / "run_channel_split_production.sh"
TIMER = ROOT / "deploy" / "systemd" / "channel-split-prod-alan-daily-digest.timer"


class DailyDigestProductionWiringTests(unittest.TestCase):
    def test_publisher_exposes_dedicated_digest_post(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn('"alanchande-daily-digest"', text)
        self.assertIn('add_alanchande(text, "daily-digest", safety)', text)
        self.assertIn('collect_digest(history_db)', text)

    def test_digest_history_advances_only_after_verified_send(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        marker = 'if "daily-digest" in verified_sent_market_posts:'
        self.assertIn(marker, text)
        block = text[text.index(marker): text.index("if send_failures:", text.index(marker))]
        self.assertIn('record_published_values(', block)
        self.assertIn('"daily-digest"', block)
        self.assertIn("daily_digest_publish_cache", block)

    def test_production_launcher_allows_digest(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("alanchande-daily-digest", text)
        self.assertIn("export MARKET_SAFETY_MODE=enforce", text)
        self.assertIn("export MARKET_HISTORY_DB=market_history_production.sqlite3", text)

    def test_timer_is_once_daily_at_1205_tehran_and_nonpersistent(self):
        text = TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 12:05:00 Asia/Tehran", text)
        self.assertIn("Persistent=false", text)
        self.assertIn(
            "Unit=channel-split-production@alanchande-daily-digest.service",
            text,
        )


if __name__ == "__main__":
    unittest.main()
