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
        self.assertIn('06) post="alanchande-turkey-gold"', script)
        self.assertIn('12) post="alanchande-fx-pulse"', script)
        self.assertIn('18) post="alanchande-iran-gold"', script)
        self.assertNotIn('post="alanchande-iran-fx"', script)
        self.assertNotIn('post="alanchande-usdt-exchanges"', script)
        self.assertIn("OnCalendar=*-*-* 00/6:50:00 Europe/Istanbul", timer)

    def test_fast_shadow_boards_have_independent_cadence(self):
        launcher = (
            ROOT / "channel_split" / "run_alanchande_shadow_post.sh"
        ).read_text(encoding="utf-8")
        usdt_timer = (
            ROOT / "deploy" / "systemd" / "alanchande-shadow-usdt.timer"
        ).read_text(encoding="utf-8")
        iran_fx_timer = (
            ROOT / "deploy" / "systemd" / "alanchande-shadow-iran-fx.timer"
        ).read_text(encoding="utf-8")

        self.assertIn("ALANCHANDE_CHANNEL_ID=@alanchandetest", launcher)
        self.assertIn("MARKET_SAFETY_MODE=shadow", launcher)
        self.assertIn("MARKET_HISTORY_DB=market_history_shadow.sqlite3", launcher)
        self.assertIn("alanchande-usdt-exchanges|alanchande-iran-fx", launcher)
        self.assertIn("OnCalendar=*-*-* *:10:00 Europe/Istanbul", usdt_timer)
        self.assertIn("OnCalendar=*-*-* 00/2:30:00 Europe/Istanbul", iran_fx_timer)

    def test_rapid_rotation_is_test_only_and_covers_all_posts(self):
        script = (
            ROOT / "channel_split" / "run_channel_split_rapid_test.sh"
        ).read_text(encoding="utf-8")
        timer = (
            ROOT / "deploy" / "systemd" / "channel-split-rapid-test.timer"
        ).read_text(encoding="utf-8")

        self.assertIn("ALANCHANDE_CHANNEL_ID=@alanchandetest", script)
        self.assertIn("KIANI_CHANNEL_ID=@kianiexchangetest", script)
        self.assertIn("MARKET_SAFETY_MODE=shadow", script)
        self.assertIn("MARKET_HISTORY_DB=market_history_shadow.sqlite3", script)
        self.assertIn("flock -n 9", script)
        for post in (
            "bank-comparison",
            "kiani-try",
            "alanchande-iran-fx",
            "kiani-rates",
            "alanchande-turkey-gold",
            "kiani-examples",
            "alanchande-usdt-exchanges",
            "kiani-examples-reverse",
            "alanchande-fx-pulse",
            "alanchande-iran-gold",
        ):
            self.assertIn(f'post="{post}"', script)

        self.assertIn(
            "OnCalendar=*-*-* *:00/3:00 Europe/Istanbul",
            timer,
        )

    def test_production_launcher_is_guarded_and_enforced(self):
        script = (
            ROOT / "channel_split" / "run_channel_split_production.sh"
        ).read_text(encoding="utf-8")
        service = (
            ROOT / "deploy" / "systemd" / "channel-split-production@.service"
        ).read_text(encoding="utf-8")

        self.assertIn("ALANCHANDE_CHANNEL_ID=@alanchande_com", script)
        self.assertIn("KIANI_CHANNEL_ID=@ExchangeKiani", script)
        self.assertIn("MARKET_SAFETY_MODE=enforce", script)
        self.assertIn("MARKET_HISTORY_DB=market_history.sqlite3", script)
        self.assertIn("flock -n 9", script)
        self.assertIn("ExecStart=/bin/bash", service)

    def test_production_timers_match_requested_cadence(self):
        expected = {
            "channel-split-prod-alan-iran-fx.timer":
                "OnCalendar=*-*-* 09..21:00:00 Asia/Tehran",
            "channel-split-prod-alan-usdt.timer":
                "OnCalendar=*-*-* 09..21:30:00 Asia/Tehran",
            "channel-split-prod-kiani-try.timer":
                "OnCalendar=*-*-* 09..21:10:00 Asia/Tehran",
            "channel-split-prod-kiani-rates.timer":
                "OnCalendar=*-*-* 09..21:40:00 Asia/Tehran",
            "channel-split-prod-alan-bank.timer":
                "OnCalendar=*-*-* 09:20:00 Asia/Tehran",
            "channel-split-prod-alan-turkey-gold.timer":
                "OnCalendar=*-*-* 11:50:00 Asia/Tehran",
            "channel-split-prod-alan-fx-pulse.timer":
                "OnCalendar=*-*-* 16:20:00 Asia/Tehran",
            "channel-split-prod-alan-iran-gold.timer":
                "OnCalendar=*-*-* 20:20:00 Asia/Tehran",
            "channel-split-prod-kiani-try-example.timer":
                "OnCalendar=*-*-* 11:15:00 Asia/Tehran",
            "channel-split-prod-kiani-toman-example.timer":
                "OnCalendar=*-*-* 17:15:00 Asia/Tehran",
        }
        for filename, schedule in expected.items():
            timer = (
                ROOT / "deploy" / "systemd" / filename
            ).read_text(encoding="utf-8")
            self.assertIn(schedule, timer)
            self.assertIn("Persistent=false", timer)
            self.assertNotIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()
