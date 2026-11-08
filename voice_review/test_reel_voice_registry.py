from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch

import reel_voice_registry as registry
import reel_voice_review as sheets
import reel_voice_samples as samples
import reel_voice_telegram as telegram


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'voices.sqlite3'
        self.con = registry.connect(self.path)
        registry.seed(self.con)
        self.sample = self.root / 'sample.wav'
        with wave.open(str(self.sample), 'wb') as stream:
            stream.setparams((1, 2, 24000, 24000, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0' * 24000)

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def verify_four(self):
        data = [{'name': name, 'voice_id': voice_id} for name, voice_id in registry.CANDIDATES if voice_id]
        registry.refresh_access(self.con, data)

    def approve(self, name, scores=None):
        registry.save_sample(self.con, name, self.sample)
        return registry.review(self.con, name, scores or {item: 8 for item in registry.CRITERIA},
                               'reviewed', serious_error=False, approved=True, enabled=True)

    def test_candidates_start_unverified_and_inactive(self):
        voices = registry.list_voices(self.con)
        self.assertEqual(len(voices), 13)
        self.assertTrue(all(not row['approved'] and not row['enabled'] and not row['verified'] for row in voices))
        self.assertTrue(all(not row['voice_id'] for row in voices if row['name'] in {'Mard', 'Mitra'}))
        with self.assertRaises(registry.RegistryError):
            registry.select(self.con, 'test-job')

    def test_weighted_scoring_and_invalid_values(self):
        self.assertEqual(registry.score(dict(zip(registry.CRITERIA, (10, 8, 6, 4)))), 76)
        for values in ({}, {key: 11 for key in registry.CRITERIA}, {key: float('nan') for key in registry.CRITERIA}):
            with self.assertRaises(registry.RegistryError):
                registry.score(values)

    def test_new_id_requires_explicit_confirmation_even_after_refresh(self):
        candidate = {'name': 'Mahdi', 'voice_id': 'a' * 20}
        registry.refresh_access(self.con, [candidate])
        registry.refresh_access(self.con, [candidate])
        voice = next(v for v in registry.list_voices(self.con) if v['name'] == 'Mahdi')
        self.assertTrue(voice['available'])
        self.assertFalse(voice['verified'])
        registry.confirm_voice_id(self.con, 'Mahdi', 'a' * 20)
        self.assertTrue(next(v for v in registry.list_voices(self.con) if v['name'] == 'Mahdi')['verified'])

    def test_duplicate_names_are_not_guessed(self):
        registry.refresh_access(self.con, [{'name': 'Mahdi', 'voice_id': 'a' * 20},
                                           {'name': 'Mahdi', 'voice_id': 'b' * 20}])
        row = next(v for v in registry.list_voices(self.con) if v['name'] == 'Mahdi')
        self.assertFalse(row['available'])
        self.assertIsNone(row['voice_id'])

    def test_user_supplied_ids_match_descriptive_account_names(self):
        inventory = [
            {'name': 'Sahar - Smooth and Natural', 'voice_id': 'lIfJn0EyB8lHm00xiGY8'},
            {'name': 'Aylin - Warm Persian Narrator', 'voice_id': 'zagI4JNTfBvHyoNxaZWj'},
            {'name': 'Shahram, documentary, storytelling or neutral tone.', 'voice_id': 'rNb3hdSf0n4ROIbYC8Bl'},
            {'name': 'Adrian Mohammadi - Versatile Voice', 'voice_id': 'BognUUMX6W1qmZKB2TOw'},
        ]
        registry.refresh_access(self.con, inventory)
        voices = {v['name']: v for v in registry.list_voices(self.con)}
        for name in ('Sahar', 'Aylin', 'Shahram', 'Adrian'):
            self.assertTrue(voices[name]['available'])
            self.assertTrue(voices[name]['verified'])
            self.assertFalse(voices[name]['approved'])
            self.assertFalse(voices[name]['enabled'])

    def test_descriptive_name_matching_requires_a_name_boundary(self):
        self.assertTrue(registry.candidate_name_matches('Aran', 'Aran - Persian narrator'))
        self.assertFalse(registry.candidate_name_matches('Aran', 'Aramofen'))
        self.assertFalse(registry.candidate_name_matches('Mitra', 'Mitrabelle'))

    def test_score_does_not_auto_approve_and_serious_errors_block_approval(self):
        self.verify_four()
        registry.save_sample(self.con, 'Sahar', self.sample)
        scores = {item: 10 for item in registry.CRITERIA}
        registry.review(self.con, 'Sahar', scores, '', serious_error=False, approved=False, enabled=False)
        self.assertFalse(next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')['approved'])
        with self.assertRaises(registry.RegistryError):
            registry.review(self.con, 'Sahar', scores, '', serious_error=True, approved=True, enabled=True)
        with self.assertRaises(registry.RegistryError):
            registry.review(self.con, 'Sahar', {item: 7 for item in registry.CRITERIA}, '',
                            serious_error=False, approved=True, enabled=True)
        with self.assertRaises(registry.RegistryError):
            registry.review(self.con, 'Sahar', scores, '', serious_error=False, approved=False, enabled=True)

    def test_sample_change_invalidates_approval(self):
        self.verify_four()
        self.approve('Sahar')
        registry.save_sample(self.con, 'Sahar', self.sample)
        self.assertTrue(next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')['approved'])
        with wave.open(str(self.sample), 'wb') as stream:
            stream.setparams((1, 2, 24000, 24000, 'NONE', 'not compressed'))
            stream.writeframes(b'\1\0' * 24000)
        registry.save_sample(self.con, 'Sahar', self.sample)
        row = next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')
        self.assertFalse(row['approved'])
        self.assertFalse(row['enabled'])

    def test_selection_is_persistent_idempotent_and_avoids_consecutive_voice(self):
        self.verify_four()
        self.approve('Sahar')
        self.approve('Aylin')
        first = registry.select(self.con, 'job-1')
        self.assertEqual(first['voice_id'], registry.select(self.con, 'job-1')['voice_id'])
        registry.mark_published(self.con, 'job-1', '123456789')
        self.con.close()
        self.con = registry.connect(self.path)
        second = registry.select(self.con, 'job-2')
        self.assertNotEqual(first['voice_id'], second['voice_id'])
        with self.assertRaises(registry.RegistryError):
            registry.select(self.con, 'job-2', override=first['voice_id'])

    def test_unavailable_or_disabled_voice_cannot_be_selected(self):
        self.verify_four()
        self.approve('Sahar')
        registry.refresh_access(self.con, [])
        with self.assertRaises(registry.RegistryError):
            registry.select(self.con, 'job')

    def test_published_media_id_requires_confirmation_and_is_idempotent(self):
        self.verify_four()
        self.approve('Sahar')
        registry.select(self.con, 'job')
        registry.mark_published(self.con, 'job', '123456789')
        registry.mark_published(self.con, 'job', '123456789')
        with self.assertRaises(registry.RegistryError):
            registry.mark_published(self.con, 'job', '987654321')

    def test_review_sheet_requires_explicit_human_approval(self):
        self.verify_four()
        registry.save_sample(self.con, 'Sahar', self.sample)
        sheet = self.root / 'review.json'
        sheets.export_sheet(self.con, sheet)
        data = json.loads(sheet.read_text(encoding='utf-8'))
        sahar = next(item for item in data['voices'] if item['name'] == 'Sahar')
        sahar['scores'] = {key: 10 for key in registry.CRITERIA}
        sahar['serious_error'] = False
        sheet.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(sheets.apply_sheet(self.con, sheet), 1)
        self.assertFalse(next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')['approved'])
        sahar['approved'] = True
        sahar['enabled'] = True
        sheet.write_text(json.dumps(data), encoding='utf-8')
        sheets.apply_sheet(self.con, sheet)
        self.assertTrue(next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')['enabled'])

    def test_existing_review_sheet_is_backed_up_before_export(self):
        sheet = self.root / 'review.json'
        original = b'{"unsaved_human_notes": "keep"}'
        sheet.write_bytes(original)
        backup = sheets.export_sheet(self.con, sheet)
        self.assertEqual(backup.read_bytes(), original)
        self.assertNotEqual(sheet.read_bytes(), original)

    def test_review_sheet_rejects_changed_identity_and_rolls_back(self):
        self.verify_four()
        registry.save_sample(self.con, 'Sahar', self.sample)
        sheet = self.root / 'review.json'
        sheets.export_sheet(self.con, sheet)
        data = json.loads(sheet.read_text(encoding='utf-8'))
        sahar = next(item for item in data['voices'] if item['name'] == 'Sahar')
        sahar['scores'] = {key: 10 for key in registry.CRITERIA}
        sahar['serious_error'] = False
        data['voices'].append(dict(sahar, name='unknown'))
        sheet.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(registry.RegistryError):
            sheets.apply_sheet(self.con, sheet)
        self.assertIsNone(next(v for v in registry.list_voices(self.con) if v['name'] == 'Sahar')['score'])

    def test_comparison_allows_unverified_candidate_but_not_approval(self):
        registry.refresh_access(self.con, [{'name': 'Mahdi', 'voice_id': 'a' * 20}])
        fake = {'audio': self.sample.read_bytes(), 'starts': [], 'cached': False}
        with patch('reel_voice_samples.synthesize_segment', return_value=fake) as request:
            results = samples.generate(self.con, self.root / 'samples', self.root / 'cache', 'test-key')
        mahdi = next(item for item in results if item['name'] == 'Mahdi')
        self.assertEqual(mahdi['status'], 'ready')
        self.assertFalse(mahdi['identity_confirmed'])
        self.assertEqual(request.call_count, 1)
        with self.assertRaises(registry.RegistryError):
            registry.review(self.con, 'Mahdi', {item: 10 for item in registry.CRITERIA}, '',
                            serious_error=False, approved=True, enabled=True)

    def test_private_telegram_verifies_identity_and_sends_each_sample_once(self):
        self.verify_four()
        registry.save_sample(self.con, 'Sahar', self.sample)
        calls = []
        def request(token, method, *, fields=None, audio=None):
            calls.append((method, fields))
            if method == 'getMe':
                return {'username': 'EnPevobot', 'id': 12345}
            if method == 'getChat':
                return {'id': telegram.CHAT_ID, 'type': 'channel', 'title': 'en movie test'}
            if method == 'getChatMember':
                return {'status': 'administrator', 'can_post_messages': True}
            self.assertEqual(fields['chat_id'], telegram.CHAT_ID)
            self.assertIn('Sahar | eleven_v4', fields['caption'])
            self.assertEqual(audio[4:8], b'ftyp')
            return {'message_id': 123}
        self.assertEqual(telegram.deliver(self.con, 'private', request=request)[0]['status'], 'sent')
        self.assertEqual(telegram.deliver(self.con, 'private', request=request)[0]['status'], 'sent')
        self.assertEqual(sum(1 for method, _ in calls if method == 'sendAudio'), 1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_telegram_upload_uses_playable_m4a(self):
        data = telegram._to_m4a(self.sample)
        output = self.root / 'converted.m4a'
        output.write_bytes(data)
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name',
                                 '-of', 'default=nw=1', str(output)], capture_output=True, timeout=20, check=True)
        self.assertIn(b'codec_name=aac', result.stdout)

    def test_telegram_unknown_outcome_is_not_retried(self):
        self.verify_four()
        registry.save_sample(self.con, 'Sahar', self.sample)
        calls = []
        def request(token, method, *, fields=None, audio=None):
            calls.append(method)
            if method == 'getMe':
                return {'username': 'EnPevobot', 'id': 12345}
            if method == 'getChat':
                return {'id': telegram.CHAT_ID, 'type': 'channel', 'title': 'en movie test'}
            if method == 'getChatMember':
                return {'status': 'administrator', 'can_post_messages': True}
            raise telegram.TelegramError('uncertain')
        self.assertEqual(telegram.deliver(self.con, 'private', request=request)[0]['status'], 'unknown_needs_review')
        self.assertEqual(telegram.deliver(self.con, 'private', request=request)[0]['status'], 'unknown')
        self.assertEqual(calls.count('sendAudio'), 1)

    def test_telegram_wrong_channel_never_sends(self):
        def request(token, method, *, fields=None, audio=None):
            if method == 'getMe':
                return {'username': 'EnPevobot', 'id': 12345}
            if method == 'getChat':
                return {'id': telegram.CHAT_ID, 'type': 'channel', 'title': 'wrong'}
            self.fail('No sample should be sent')
        with self.assertRaises(telegram.TelegramError):
            telegram.deliver(self.con, 'private', request=request)

    def test_telegram_bot_without_post_permission_never_sends(self):
        def request(token, method, *, fields=None, audio=None):
            if method == 'getMe':
                return {'username': 'EnPevobot', 'id': 12345}
            if method == 'getChat':
                return {'id': telegram.CHAT_ID, 'type': 'channel', 'title': 'en movie test'}
            if method == 'getChatMember':
                return {'status': 'administrator', 'can_post_messages': False}
            self.fail('No sample should be sent')
        with self.assertRaises(telegram.TelegramError):
            telegram.deliver(self.con, 'private', request=request)


if __name__ == '__main__':
    unittest.main()

