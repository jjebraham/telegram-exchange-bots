from datetime import datetime, timezone
from pathlib import Path
import json
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import reel_elevenlabs as eleven
import reel_local_settings as settings
import reel_narration_usage as usage
import reel_voice_performance as performance


class AccountingTests(unittest.TestCase):
    def test_lost_response_does_not_create_another_billable_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.sqlite3'
            with patch.object(eleven, '_generate', side_effect=eleven.VoiceError('uncertain')) as request:
                with self.assertRaises(eleven.VoiceError):
                    eleven.synthesize_segment('متن آزمایشی', path, 'test-key')
                with self.assertRaises(ValueError):
                    eleven.synthesize_segment('متن آزمایشی', path, 'test-key')
                self.assertEqual(request.call_count, 1)
            result = usage.report(path)
            self.assertEqual(result['requests'], 1)
            self.assertGreater(result['submitted_characters'], 0)
            self.assertEqual(result['unconfirmed_requests'], 1)

    def test_character_cap_is_checked_before_a_new_request_and_counts_uncertain_calls(self):
        con = sqlite3.connect(':memory:', isolation_level=None)
        usage.schema(con)
        now = datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp()
        with patch.dict(os.environ, {'REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT': '100'}):
            con.execute('BEGIN IMMEDIATE')
            usage.reserve(con, 'a', 'voice', 'eleven_v4', 70, now=now)
            con.commit()
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(ValueError, 'limit'):
                usage.reserve(con, 'b', 'voice', 'eleven_v4', 31, now=now)
            con.rollback()
            con.execute('BEGIN IMMEDIATE')
            usage.reserve(con, 'c', 'voice', 'eleven_v4', 100, now=now + 31 * 86400)
            con.commit()
        self.assertEqual(con.execute('SELECT COUNT(*) FROM narration_requests').fetchone()[0], 2)
        con.close()

    def test_received_audio_is_reused_after_local_processing_fails(self):
        from test_reel_elevenlabs import sample
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.sqlite3'
            with patch.object(eleven, '_generate', side_effect=sample) as request:
                with patch.object(eleven, '_probe', side_effect=eleven.VoiceError('local error')):
                    with self.assertRaises(eleven.VoiceError):
                        eleven.synthesize_segment('سلام', path, 'test-key')
                with patch.object(eleven, '_probe', side_effect=eleven.VoiceError('local error')):
                    with self.assertRaises(eleven.VoiceError):
                        eleven.synthesize_segment('سلام', path, 'test-key')
                self.assertEqual(request.call_count, 1)


class SettingsTests(unittest.TestCase):
    def test_installer_keeps_posting_slots_and_scopes_analytics_to_its_cron_block(self):
        file = Path(__file__).parent / 'deploy/instagram-trial-reels/activate_trial_reels.py'
        spec = importlib.util.spec_from_file_location('voice_activation_test', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = b'5 7 * * * /home/example/another-post.sh\n'
        commands = ['* * * * * /home/example/run-kiani-instagram-reel-schedule.sh',
                    '*/30 * * * * /home/example/run-kiani-instagram-voice-insights.sh']
        changed = module.replace_trial_cron(original, commands)
        self.assertTrue(changed.startswith(original))
        self.assertEqual(module.replace_trial_cron(changed, commands), changed)
        with self.assertRaises(RuntimeError):
            module.replace_trial_cron(changed + b'* * * * * /home/example/run-kiani-instagram-voice-insights.sh\n', commands)

    def test_persistent_enable_and_disable_preserve_cap_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'local-render.env'
            original = 'REEL_ELEVENLABS_ENABLED=false\nREEL_ELEVENLABS_MONTHLY_CHAR_LIMIT=10000\n'
            path.write_text(original)
            path.chmod(0o600)
            backup = settings.configure(True, path)
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(settings.read(path)['REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT'], '10000')
            self.assertEqual(settings.read(path)['REEL_ELEVENLABS_ENABLED'], 'true')
            settings.configure(False, path)
            self.assertEqual(settings.read(path)['REEL_ELEVENLABS_ENABLED'], 'false')

    def test_missing_configuration_keeps_old_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(settings.read(Path(tmp) / 'absent.env'), {})

    def test_settings_are_parsed_as_data_and_reject_runpod_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'local-render.env'
            path.write_text('REEL_ELEVENLABS_ENABLED=true\nREEL_MUSIC_VOLUME=0.20\n')
            path.chmod(0o600)
            self.assertEqual(settings.read(path)['REEL_ELEVENLABS_ENABLED'], 'true')
            for invalid in ('RUNPOD_API_KEY=x', 'REEL_ELEVENLABS_ENABLED=$(anything)', 'ELEVENLABS_MODEL=eleven_v3', 'REEL_MUSIC_VOLUME=nan'):
                path.write_text(invalid + '\n')
                with self.assertRaises(ValueError):
                    settings.read(path)


class PerformanceTests(unittest.TestCase):
    def row(self, voice, media='12345', **changes):
        result = {'voice_json': json.dumps({'name': voice}), 'media_id': media,
                  'published_at': 1794222000.0, 'duration_seconds': 25,
                  'kind': 'crypto', 'reel_mode': 'trial', 'title_original': 'Bitcoin news'}
        return dict(result, **changes)

    def test_missing_metrics_are_not_zero_and_age_windows_do_not_mix(self):
        a, b = self.row('Sahar'), self.row('Aylin', '23456')
        samples = [{'media_id': '12345', 'observed_at': a['published_at'] + 25*3600,
                    'metrics': {'views': 100, 'reach': 80, 'likes': 2, 'comments': 0, 'saved': 0, 'shares': 2}},
                   {'media_id': '23456', 'observed_at': b['published_at'] + 4*3600, 'metrics': {'views': 999}}]
        report = performance.comparison([a, b], samples)
        self.assertEqual(len(report['voices']), 1)
        voice = report['voices'][0]
        self.assertEqual(voice['median_views'], 100)
        self.assertEqual(voice['median_engagement_rate'], .05)
        self.assertIsNone(voice['median_completion_rate'])
        self.assertFalse(report['selection_probabilities_changed'])

    def test_comparisons_group_topic_length_mode_and_publication_time(self):
        a = self.row('Sahar')
        b = self.row('Aylin', '23456')
        c = self.row('Adrian', '34567', title_original='AI models', duration_seconds=80)
        samples = [{'media_id': r['media_id'], 'observed_at': r['published_at'] + 24*3600,
                    'metrics': {'views': 100}} for r in (a, b, c)]
        report = performance.comparison([a, b, c], samples)
        self.assertEqual(len(report['comparable_strata']), 1)
        self.assertEqual(set(report['comparable_strata'][0]['voices']), {'Sahar', 'Aylin'})

    def test_collection_is_checkpointed_and_reads_only_confirmed_published_rows(self):
        a = self.row('Sahar')
        class Graph:
            account_id = '11111'
            calls = 0
            def metrics(self, media, names):
                self.calls += 1
                return {'observed_at': a['published_at'] + 24*3600,
                        'metrics': {name: {'value': 0} for name in names}}
        graph = Graph()
        con = sqlite3.connect(':memory:')
        self.assertEqual(performance.collect([a], graph, con, now=a['published_at']+24*3600), 1)
        self.assertEqual(performance.collect([a], graph, con, now=a['published_at']+25*3600), 0)
        self.assertEqual(graph.calls, 1)
        con.close()


if __name__ == '__main__':
    unittest.main()
