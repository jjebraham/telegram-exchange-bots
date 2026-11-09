import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
usage = types.ModuleType('instagram_reel_usage')
usage.tracked = lambda *args, **kwargs: lambda function: function
sys.modules.setdefault('instagram_reel_usage', usage)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'news-python-libs'))
import instagram_trial_reels as trial
import reel_voice_registry as voices


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_patch = patch.object(trial, 'STATE', self.root)
        self.state_patch.start()
        self.db = self.root / 'voices.sqlite3'
        self.con = voices.connect(self.db)
        voices.seed(self.con)
        voices.refresh_access(self.con, [{'name': 'Sahar - Smooth and Natural',
                                        'voice_id': 'lIfJn0EyB8lHm00xiGY8'}])
        self.wav = self.root / 'sample.wav'
        with wave.open(str(self.wav), 'wb') as out:
            out.setparams((1, 2, 24000, 24000, 'NONE', 'not compressed'))
            out.writeframes(b'\0\0' * 24000)

    def tearDown(self):
        self.state_patch.stop()
        self.con.close()
        self.temp.cleanup()

    def approve(self):
        voices.save_sample(self.con, 'Sahar', self.wav)
        voices.review(self.con, 'Sahar', {name: 8 for name in voices.CRITERIA}, 'test',
                      serious_error=False, approved=True, enabled=True)

    def test_new_jobs_require_an_approved_voice(self):
        with patch.object(trial, '_voice_registry_path', return_value=self.db), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(trial.TrialReelError):
                trial._select_narrator('job-a')
            self.approve()
            selected = trial._select_narrator('job-a')
            self.assertEqual(selected['voice_id'], 'lIfJn0EyB8lHm00xiGY8')
            self.assertEqual(trial._select_narrator('job-a')['voice_id'], selected['voice_id'])

    def test_manual_override_cannot_bypass_approval(self):
        with patch.object(trial, '_voice_registry_path', return_value=self.db), \
                patch.dict(os.environ, {'REEL_VOICE_OVERRIDE': 'lIfJn0EyB8lHm00xiGY8'}, clear=True):
            with self.assertRaises(trial.TrialReelError):
                trial._select_narrator('job-b')

    def test_narration_uses_same_selected_voice_for_all_cards(self):
        story = {'title_fa': 'خبر آزمایشی', 'summary_fa': 'این یک خبر آزمایشی است.'}
        output = {'audio': self.wav.read_bytes(), 'starts': [0, .5], 'cached': False}
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), \
                patch('reel_elevenlabs.synthesize_segment', return_value=output) as synth, \
                patch.object(trial, '_narrated_chunks', return_value=[story['summary_fa']]):
            result = trial._prepare_narration(story, self.root, 'lIfJn0EyB8lHm00xiGY8', self.root, has_images=True)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(call.kwargs['voice_id'] == 'lIfJn0EyB8lHm00xiGY8' for call in synth.call_args_list))
        self.assertTrue(all(call.kwargs['model'] == 'eleven_v4' for call in synth.call_args_list))

    def test_unreviewed_model_or_speed_stops_before_synthesis(self):
        story = {'title_fa': 'خبر آزمایشی', 'summary_fa': 'این یک خبر آزمایشی است.'}
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key', 'ELEVENLABS_MODEL': 'eleven_v3'}, clear=True), \
                patch('reel_elevenlabs.synthesize_segment') as synth:
            with self.assertRaises(trial.TrialReelError):
                trial._prepare_narration(story, self.root, 'lIfJn0EyB8lHm00xiGY8', self.root, has_images=True)
            synth.assert_not_called()

    def test_one_pronunciation_pass_is_used_without_modifying_visible_story(self):
        story = {'title_fa': 'احتمال در اختیار داشتن کلید', 'summary_fa': 'خبر آزمایشی گزارش شد.'}
        original = dict(story)
        spoken = ['احتمالِ در اختیار داشتن کلید', 'خَبَر آزمایشی گزارش شد.']
        output = {'audio': self.wav.read_bytes(), 'starts': [0, .5], 'cached': False}
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), \
                patch('reel_persian_pronunciation.prepare', return_value=(spoken, 'prepared')) as marks, \
                patch('reel_elevenlabs.synthesize_segment', return_value=output) as synth, \
                patch.object(trial, '_narrated_chunks', return_value=[story['summary_fa']]):
            result = trial._prepare_narration(story, self.root, 'lIfJn0EyB8lHm00xiGY8', self.root, has_images=True)
        self.assertEqual(story, original)
        self.assertEqual(marks.call_count, 1)
        self.assertEqual([call.kwargs['spoken_script'] for call in synth.call_args_list], spoken)
        self.assertTrue(all(segment['pronunciation_status'] == 'prepared' for segment in result))

    def test_narration_preparation_never_loads_a_deepseek_key_from_home(self):
        story = {'title_fa': 'خبر آزمایشی', 'summary_fa': 'این خبر تأیید شده است.'}
        output = {'audio': self.wav.read_bytes(), 'starts': [0, .5], 'cached': False}
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), \
                patch('pathlib.Path.home', side_effect=AssertionError('Must not read production credentials')), \
                patch('reel_persian_pronunciation._request', side_effect=AssertionError('Offline test must not call DeepSeek')) as request, \
                patch('reel_elevenlabs.synthesize_segment', return_value=output), \
                patch.object(trial, '_narrated_chunks', return_value=[story['summary_fa']]):
            result = trial._prepare_narration(story, self.root, 'lIfJn0EyB8lHm00xiGY8', self.root, has_images=True)
        self.assertEqual(result[0]['pronunciation_status'], 'fallback_no_key')
        request.assert_not_called()

    def test_sentence_chunks_are_complete_and_text_is_preserved(self):
        local_assets = Path(__file__).resolve().parent.parent / 'telegram-exchange-bots-instagram'
        assets = local_assets if (local_assets / 'fonts/Vazirmatn-Regular.ttf').is_file() else Path.home() / 'kiani-instagram-publisher'
        if not (assets / 'fonts/Vazirmatn-Regular.ttf').is_file():
            self.skipTest('Production fonts are unavailable')
        sentences = [
            'بیت کوین امروز پس از افزایش تقاضا رشد کرد.',
            'معامله گران اکنون شرایط بازار را با دقت بیشتری بررسی می کنند.',
            'ارزش معاملات در ساعات گذشته افزایش داشته است.',
            'کارشناسان درباره نوسان قیمت در روزهای آینده هشدار داده اند.',
            'بررسی اطلاعات در گزارش رسمی ادامه دارد.',
        ]
        text = ' '.join(sentences)
        chunks = trial._narrated_chunks(text, assets, has_images=True, limit=100)
        self.assertEqual(' '.join(chunks), text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.endswith('.') for chunk in chunks))
        self.assertTrue(all(sentence in chunks[next(i for i, c in enumerate(chunks) if sentence in c)]
                            for sentence in sentences))
        long_sentence = ('بازار ' * 30) + 'رشد کرد.'
        self.assertGreater(len(long_sentence), 170)
        self.assertEqual(trial._narrated_chunks(long_sentence, assets, has_images=True), [long_sentence])
        abbreviation = 'Dr. Smith بازار را بررسی کرد. سپس گزارش ارائه شد.'
        abbreviation_chunks = trial._narrated_chunks(abbreviation, assets, has_images=True, limit=25)
        self.assertTrue(abbreviation_chunks[0].startswith('Dr. Smith'))
        self.assertEqual(' '.join(abbreviation_chunks), abbreviation)

    def test_overlong_sentence_fails_before_any_audio_request(self):
        local_assets = Path(__file__).resolve().parent.parent / 'telegram-exchange-bots-instagram'
        assets = local_assets if (local_assets / 'fonts/Vazirmatn-Regular.ttf').is_file() else Path.home() / 'kiani-instagram-publisher'
        if not (assets / 'fonts/Vazirmatn-Regular.ttf').is_file():
            self.skipTest('Production fonts are unavailable')
        story = {'title_fa': 'خبر آزمایشی', 'summary_fa': ('بازار ' * 500).strip() + '.'}
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test-key'}, clear=True), \
                patch('reel_elevenlabs.synthesize_segment') as synth:
            with self.assertRaises(trial.TrialReelError):
                trial._prepare_narration(story, self.root, 'lIfJn0EyB8lHm00xiGY8', assets, has_images=True)
            synth.assert_not_called()

    def test_reconciliation_records_only_confirmed_published_media(self):
        self.approve()
        voices.select(self.con, 'job-confirmed')
        voices.select(self.con, 'job-pending')
        voices.select(self.con, 'job-failed')
        main = sqlite3.connect(':memory:')
        main.row_factory = sqlite3.Row
        main.execute('CREATE TABLE trial_reels(trial_id TEXT,status TEXT,media_id TEXT)')
        main.executemany('INSERT INTO trial_reels VALUES(?,?,?)', [
            ('job-confirmed', 'published', '123456789'),
            ('job-pending', 'container_processing', None),
            ('job-failed', 'failed', None),
        ])
        try:
            with patch.object(trial, '_voice_registry_path', return_value=self.db):
                trial._reconcile_published_voice_history(main)
            rows = {r['job_id']: dict(r) for r in self.con.execute('SELECT * FROM selections')}
            self.assertEqual(rows['job-confirmed']['status'], 'published')
            self.assertEqual(rows['job-confirmed']['media_id'], '123456789')
            self.assertEqual(rows['job-pending']['status'], 'reserved')
            self.assertEqual(rows['job-failed']['status'], 'failed')
        finally:
            main.close()


if __name__ == '__main__':
    unittest.main()
