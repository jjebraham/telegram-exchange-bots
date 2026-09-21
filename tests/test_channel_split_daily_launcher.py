import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DailyLauncherTests(unittest.TestCase):
    def test_launcher_is_lock_protected_and_calls_daily_bundle(self):
        script = (ROOT / "channel_split" / "run_alanchande_daily.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("set -euo pipefail", script)
        self.assertIn("flock -n 9", script)
        self.assertIn("--post alanchande-daily", script)
        self.assertIn('cd "$SCRIPT_DIR"', script)

    def test_systemd_service_uses_bash_launcher(self):
        service = (
            ROOT / "deploy" / "systemd" / "alanchande-daily.service"
        ).read_text(encoding="utf-8")

        self.assertIn("Type=oneshot", service)
        self.assertIn("User=kianirad2020", service)
        self.assertIn(
            "ExecStart=/bin/bash /home/kianirad2020/telegram_bot_repo/channel_split/run_alanchande_daily.sh",
            service,
        )
        self.assertNotIn("OnCalendar=", service)


if __name__ == "__main__":
    unittest.main()
