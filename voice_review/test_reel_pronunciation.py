from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reel_narration_timing import TimingError, apply_diacritics, build_script, word_starts
import reel_persian_pronunciation as pronunciation
import reel_elevenlabs as eleven


class MappingTests(unittest.TestCase):
    def test_ezafe_marks_are_speech_only_and_offsets_remain_exact(self):
        display = 'احتمال در اختیار داشتن کلید توسط سارق'
        script, tokens = build_script(display)
        marked, mapped = apply_diacritics(script, tokens, display.replace('احتمال', 'احتمالِ'))
        self.assertEqual(marked, 'احتمالِ در اختیار داشتن کلید توسط سارق')
        self.assertEqual([t.text for t in mapped], display.split())
        self.assertEqual(mapped[0].spoken, 'احتمالِ')
        for token in mapped:
            self.assertEqual(marked[token.start:token.end], token.spoken)

    def test_numbers_dates_and_existing_marks_are_preserved(self):
        display = 'احتمالِ رشد ۲۹٪ در ۲۰۲۶-۱۱-۰۸'
        script, tokens = build_script(display)
        marked, mapped = apply_diacritics(script, tokens, script.replace('رشد', 'رُشد').replace('بیست', 'بیستِ'))
        self.assertEqual([t.text for t in mapped], display.split())
        self.assertEqual(len(mapped), 5)
        self.assertIn('درصد', mapped[2].spoken)
        self.assertIn('نوامبر', mapped[4].spoken)
        with self.assertRaises(TimingError):
            apply_diacritics(script, tokens, script.replace('احتمالِ', 'احتمال'))

    def test_rewriting_whitespace_numbers_or_letter_shapes_is_rejected(self):
        script, tokens = build_script('کلید در اختیار سارق نیست.')
        for candidate in (
                'کلید در اختیار سارق است.', 'کلید دراختیار سارق نیست.',
                'کليد در اختیار سارق نیست.', 'کلید  در اختیار سارق نیست.',
                'کلید در اختیار سارق نیست. خبر', '```کلید در اختیار سارق نیست.```',
                'ِکلید در اختیار سارق نیست.', 'کلید ِدر اختیار سارق نیست.',
                'کلِِید در اختیار سارق نیست.', 'کَُلید در اختیار سارق نیست.'):
            with self.subTest(candidate=candidate), self.assertRaises(TimingError):
                apply_diacritics(script, tokens, candidate)
        script, tokens = build_script('GPT-4 خبر')
        with self.assertRaises(TimingError):
            apply_diacritics(script, tokens, 'GِPT-4 خبر')

    def test_provider_alignment_may_keep_or_omit_marks_but_not_change_letters(self):
        script, tokens = build_script('احتمال ۲۹٪ رشد')
        marked, mapped = apply_diacritics(script, tokens, script.replace('احتمال', 'احتمالِ'))
        for text in (marked, script):
            alignment = {'characters': list(text), 'character_start_times_seconds': [i*.1 for i in range(len(text))],
                         'character_end_times_seconds': [i*.1+.05 for i in range(len(text))]}
            result = word_starts(marked, mapped, alignment, 20)
            self.assertEqual(len(result), len(tokens))
            expected_index = text.index('بیست')
            self.assertAlmostEqual(result[1], expected_index*.1/1.5)
        changed = marked.replace('رشد', 'افت')
        alignment = {'characters': list(changed), 'character_start_times_seconds': [0]*len(changed),
                     'character_end_times_seconds': [.1]*len(changed)}
        with self.assertRaises(TimingError):
            word_starts(marked, mapped, alignment, 1)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'pronunciation.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_one_contextual_request_for_all_sections_and_cache_reuse(self):
        sections = ['احتمال در اختیار داشتن کلید', 'رشد ۲۹٪ گزارش شد.']
        seen = []
        def request(body):
            seen.append(body)
            data = json.loads(body['messages'][1]['content'])
            self.assertEqual(data['title_context'], 'Stolen keys')
            self.assertNotIn('۲۹', data['sections'][1])
            return {'sections': [data['sections'][0].replace('احتمال', 'احتمالِ'), data['sections'][1]]}
        first, status = pronunciation.prepare(sections, self.path, context='Stolen keys', request_fn=request)
        self.assertEqual(status, 'prepared')
        second, status = pronunciation.prepare(sections, self.path, context='Stolen keys', request_fn=request)
        self.assertEqual(status, 'cached')
        self.assertEqual(first, second)
        self.assertEqual(len(seen), 1)
        self.assertIn('احتمالِ', first[0])

    def test_changed_words_fall_back_without_another_model_call(self):
        seen = []
        def request(body):
            seen.append(body)
            return {'sections': ['سارق کلید را در اختیار دارد.']}
        sections = ['احتمال در اختیار داشتن کلید']
        for _ in range(2):
            result, status = pronunciation.prepare(sections, self.path, request_fn=request)
            self.assertTrue(status.startswith('fallback'))
            self.assertEqual(result, sections)
        self.assertEqual(len(seen), 1)

    def test_lost_response_is_not_retried_automatically(self):
        seen = []
        def request(body):
            seen.append(body)
            raise TimeoutError('private provider response must not be printed')
        for _ in range(2):
            result, status = pronunciation.prepare(['خبر آزمایشی'], self.path, request_fn=request)
            self.assertEqual(result, ['خبر آزمایشی'])
            self.assertTrue(status.startswith('fallback'))
        self.assertEqual(len(seen), 1)

    def test_no_key_or_disabled_feature_never_calls_the_model(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(pronunciation, '_request') as request:
            self.assertEqual(pronunciation.prepare(['خبر'], self.path)[1], 'fallback_no_key')
            self.assertFalse(self.path.exists())
            request.assert_not_called()
        with patch.dict(os.environ, {'REEL_PRONUNCIATION_ENABLED': 'false'}, clear=True), patch.object(pronunciation, '_request') as request:
            self.assertEqual(pronunciation.prepare(['خبر'], self.path)[1], 'disabled')
            request.assert_not_called()

    def test_cached_result_is_revalidated_before_use(self):
        pronunciation.prepare(['خبر آزمایشی'], self.path, request_fn=lambda body: {'sections': ['خَبَر آزمایشی']})
        con = sqlite3.connect(self.path)
        try:
            con.execute('UPDATE pronunciation SET result_json=?', (json.dumps(['خبر ساختگی']),))
            con.commit()
        finally:
            con.close()
        result, status = pronunciation.prepare(['خبر آزمایشی'], self.path, request_fn=lambda body: self.fail('Must not recharge'))
        self.assertEqual(result, ['خبر آزمایشی'])
        self.assertEqual(status, 'fallback_unverified')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_elevenlabs_receives_marked_text_and_caches_it_separately(self):
        from test_reel_elevenlabs import sample
        seen = []
        def generate(script, *args):
            seen.append(script)
            return sample(script, *args)
        audio_cache = self.path.parent / 'audio.sqlite3'
        with patch.object(eleven, '_generate', side_effect=generate):
            plain = eleven.synthesize_segment('احتمال رشد', audio_cache, 'test-key')
            marked = eleven.synthesize_segment('احتمال رشد', audio_cache, 'test-key', spoken_script='احتمالِ رشد')
            cached = eleven.synthesize_segment('احتمال رشد', audio_cache, 'test-key', spoken_script='احتمالِ رشد')
            self.assertEqual(seen, ['احتمال رشد', 'احتمالِ رشد'])
            self.assertEqual(marked['script'], 'احتمالِ رشد')
            self.assertTrue(cached['cached'])
            self.assertNotEqual(plain['cache_key'], marked['cache_key'])
            self.assertEqual(len(marked['starts']), 2)


if __name__ == '__main__':
    unittest.main()
