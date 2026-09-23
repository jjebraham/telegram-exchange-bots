"""Production timer regression checks."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
IRAN_GOLD_TIMER = (
    ROOT / "deploy" / "systemd" / "channel-split-prod-alan-iran-gold.timer"
)


class ProductionTimerTests(unittest.TestCase):
    def test_iran_gold_only_runs_once_daily_at_0930_tehran(self):
        text = IRAN_GOLD_TIMER.read_text(encoding="utf-8")
        schedule = [
            line for line in text.splitlines()
            if line.startswith("OnCalendar=")
        ]
        self.assertEqual(schedule, ["OnCalendar=*-*-* 09:30:00 Asia/Tehran"])
        self.assertIn("Persistent=false", text)
        self.assertIn(
            "Unit=channel-split-production@alanchande-iran-gold.service",
            text,
        )


if __name__ == "__main__":
    unittest.main()
