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

    def test_shadow_rotation_is_test_only_and_staggered(self):
        script = (
            ROOT / "channel_split" / "run_alanchande_shadow_test.sh"
        ).read_text(encoding="utf-8")
        timer = (
            ROOT / "deploy" / "systemd" / "alanchande-shadow-test.timer"
        ).read_text(encoding="utf-8")

        self.assertIn("ALANCHANDE_CHANNEL_ID=@alanchandetest", script)
        self.assertIn("MARKET_SAFETY_MODE=shadow", script)
        self.assertIn("MARKET_HISTORY_DB=market_history_shadow.sqlite3", script)
        self.assertIn('00) post="bank-comparison"', script)
        self.assertIn('04) post="alanchande-iran-fx"', script)
        self.assertIn('08) post="alanchande-turkey-gold"', script)
        self.assertIn('12) post="alanchande-usdt-exchanges"', script)
        self.assertIn('16) post="alanchande-fx-pulse"', script)
        self.assertIn('20) post="alanchande-iran-gold"', script)
        self.assertIn("OnCalendar=*-*-* 00/4:10:00 Europe/Istanbul", timer)


if __name__ == "__main__":
    unittest.main()
