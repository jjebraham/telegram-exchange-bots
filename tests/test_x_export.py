import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'channel_split'))
import publish_channels
from x_channel_formats import POST_TYPES


class ExportTests(unittest.TestCase):
    def test_export_requires_verified_even_with_safety_mode_off_and_never_sends(self):
        for decision in ('VERIFIED', 'BLOCKED', 'SUSPICIOUS'):
            with self.subTest(decision=decision):
                result = SimpleNamespace(text='sample', assessment=SimpleNamespace(decision=decision, reason='test'),
                                         published_values={}, source_health={})
                output = io.StringIO()
                with patch.object(sys, 'argv', ['publish_channels.py', '--post', 'alanchande-daily-digest', '--export-json']), \
                     patch.object(publish_channels, '_load_local_env'), \
                     patch.object(publish_channels, 'collect_digest', return_value=result), \
                     patch.object(publish_channels, 'telegram_send') as send, \
                     patch.object(publish_channels, 'record_published_values') as record, \
                     patch.dict('os.environ', {'MARKET_SAFETY_MODE':'off'}), \
                     contextlib.redirect_stdout(output):
                    if decision == 'VERIFIED':
                        self.assertEqual(publish_channels.main(), 0)
                        self.assertTrue(json.loads(output.getvalue())['verified'])
                    else:
                        with self.assertRaises(ValueError):
                            publish_channels.main()
                    send.assert_not_called()
                    record.assert_not_called()

    def test_eleven_once_daily_non_catchup_timers(self):
        timers = list((ROOT/'deploy/systemd').glob('kiani-x-*.timer'))
        self.assertEqual(len(timers), 11)
        for post in POST_TYPES:
            text = (ROOT/'deploy/systemd'/f'kiani-x-{post}.timer').read_text()
            self.assertEqual(text.count('OnCalendar='), 1)
            self.assertIn('Europe/Istanbul', text)
            self.assertIn('Persistent=false', text)
            self.assertIn(f'Unit=kiani-x-channel@{post}.service', text)

    def test_existing_four_slots_and_alert_schedule_preserved(self):
        text = (ROOT/'.github/workflows/daily-x-kiani-rates.yml').read_text()
        for schedule in ('12 9 * * *','7 12 * * *','12 15 * * *','12 18 * * *','37 8-22 * * *'):
            self.assertIn(f'cron: "{schedule}"', text)
        self.assertIn('X_RATE_ALERT_THRESHOLD: "0.5"', text)


if __name__ == '__main__':
    unittest.main()
