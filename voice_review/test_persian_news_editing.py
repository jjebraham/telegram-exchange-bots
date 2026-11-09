"""Offline regressions for editorial cache separation and factual constraints."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import economy_news_translation as translation
from instagram_crypto_news import NewsError
from preview_voice_reel import refresh_translation


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'editorial.sqlite3'
        self.material = dict(title_original='AI Chip Stocks Bounce After Global Rout—But Is the Bubble Starting to Burst?',
            source_text='Nvidia rose 2.78% and AMD rose 11.04%, recovering only part of the losses. A bubble collapse is not established.',
            source_name='Example source', article_date='2026-11-07')
        self.story = dict(source_url='https://example.com/chips', title_fa='بازگشت سهام تراشه ها پس از فروش گسترده',
                          summary_fa='خلاصه قدیمی خبر.')
        self.result = dict(headline_fa='سهام سازندگان تراشه‌های هوش مصنوعی بخشی از افت شدید جهانی را جبران کرد؛ آیا حباب در حال ترکیدن است؟',
            summary_fa='سهام انویدیا 2.78 درصد و سهام ای‌ام‌دی 11.04 درصد رشد کرد. این افزایش فقط بخشی از زیان پیشین را جبران کرد. گزارش هنوز ترکیدن حباب را قطعی نمی‌داند.')

    def tearDown(self):
        self.temp.cleanup()

    def test_new_prompt_bypasses_old_cache_then_reuses_reviewed_translation(self):
        seen = []
        def request(body):
            seen.append(body)
            return json.dumps(self.result, ensure_ascii=False)
        with patch.dict(os.environ, {}, clear=True):
            source = '\n'.join(self.material[k] for k in ('title_original', 'source_text', 'article_date'))
            old_key = hashlib.sha256(('economy-v2-json\ndeepseek-flash\n' + source).encode()).hexdigest()
            with closing(sqlite3.connect(self.path)) as con:
                con.execute('CREATE TABLE economy_translation_cache(input_hash TEXT PRIMARY KEY,model TEXT,title_fa TEXT,summary_fa TEXT,created_at REAL)')
                con.execute('INSERT INTO economy_translation_cache VALUES(?,?,?,?,?)', (old_key, 'deepseek-flash', 'قدیمی', 'قدیمی', 1))
                con.commit()
            revised, comparison = refresh_translation(self.story, self.material, self.path, request)
            cached, _ = refresh_translation(self.story, self.material, self.path, lambda body: self.fail('Cache should avoid a second request'))
        self.assertEqual(revised, cached)
        self.assertEqual(revised['title_fa'], self.result['headline_fa'])
        self.assertEqual(comparison['stored']['title_fa'], self.story['title_fa'])
        self.assertEqual(self.story['summary_fa'], 'خلاصه قدیمی خبر.')
        self.assertEqual(len(seen), 1)
        prompt = seen[0]['messages'][0]['content']
        for instruction in ('explicit subject', 'geographical scope', 'remain a question', 'without pronunciation vowel marks', 'silently reread'):
            self.assertIn(instruction, prompt)
        payload = json.loads(seen[0]['messages'][1]['content'])
        self.assertEqual(payload['source_text'], self.material['source_text'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM economy_translation_cache').fetchone()[0], 2)
            self.assertEqual(con.execute('SELECT title_fa FROM economy_translation_cache WHERE input_hash=?', (old_key,)).fetchone()[0], 'قدیمی')

    def test_display_text_has_no_speech_marks_and_facts_still_validate(self):
        result = dict(self.result, headline_fa=self.result['headline_fa'].replace('مصنوعی', 'مصنوعیِ'))
        title, summary = translation.validate_translation(result, self.material['source_text'])
        self.assertNotIn('مصنوعیِ', title)
        self.assertIn('مصنوعی', title)
        with self.assertRaises(NewsError):
            translation.validate_translation(dict(self.result, summary_fa=self.result['summary_fa'] + ' رشد 99 درصد بود.'), self.material['source_text'])

    def test_invalid_translation_is_not_cached_in_private_preview(self):
        with self.assertRaises(NewsError):
            refresh_translation(self.story, self.material, self.path,
                lambda body: json.dumps(dict(self.result, summary_fa=self.result['summary_fa'] + ' رشد 99 درصد بود.')))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM economy_translation_cache').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
