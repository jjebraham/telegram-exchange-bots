"""Offline caption behavior: content first, complete credits, bounded length."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'instagram_trial_reels.py').read_text(encoding='utf-8'))
NAMES = {'TrialReelError', '_safe_text', '_caption_summary', '_caption'}
NODES = [node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in NAMES]
SCOPE = {'re': re}
exec(compile(ast.Module(body=NODES, type_ignores=[]), '<offline-caption>', 'exec'), SCOPE)
caption = SCOPE['_caption']
summary = SCOPE['_caption_summary']
CaptionError = SCOPE['TrialReelError']

TITLE = 'خبر نمونه برای آزمایش کپشن فارسی'
BODY = 'این خلاصه فارسی برای آزمایش ترتیب متن خبر و منابع نوشته شده است.'
STORY = {'title_fa': TITLE, 'summary_fa': BODY, 'source_name': 'Example Publisher',
         'source_url': 'https://publisher.example/news', 'story_type': 'hard_news'}
CREDITS = (
    'برخی تصاویر این ویدئو نمادین هستند.',
    'تصویر: Example Publisher · https://publisher.example/news',
    'Photos provided by Pexels: https://www.pexels.com\nPexels: Example Author — https://photos.example/one',
    'Illustrations from Pixabay: https://pixabay.com\nPixabay: Another Author — https://photos.example/two',
    'Illustrative image: Example — Example Author; CC BY 4.0; resized/cropped. https://commons.example/image https://creativecommons.org/licenses/by/4.0/',
    'Music: Example Track — Example Composer (shortened and faded)\nhttps://music.example/track\nCC BY 4.0: https://creativecommons.org/licenses/by/4.0/',
)


class CaptionTests(unittest.TestCase):
    def test_persian_headline_and_summary_precede_source(self):
        text = caption(STORY, 'crypto')
        self.assertTrue(text.startswith(TITLE + '\n\n' + BODY + '\n\n'))
        self.assertLess(text.index(BODY), text.index('منبع:'))
        self.assertEqual(text.count(TITLE), 1)
        self.assertEqual(text.count(BODY), 1)

    def test_every_picture_and_music_credit_is_preserved_below_news(self):
        text = caption(STORY, 'crypto', extra_credits=CREDITS)
        for credit in CREDITS:
            self.assertIn(credit, text)
            self.assertGreater(text.index(credit), text.index(BODY))
        self.assertTrue(text.endswith(CREDITS[-1]))
        self.assertLessEqual(len(text), 2200)

    def test_saved_full_summary_used_when_it_fits(self):
        full = BODY + ' جمله دوم خلاصه کامل نیز بدون تغییر باقی می‌ماند.'
        text = caption(dict(STORY, full_summary_fa=full), 'economy', extra_credits=CREDITS)
        self.assertIn(TITLE + '\n\n' + full + '\n\n', text)
        self.assertEqual(text.count(full), 1)
        self.assertNotIn('نسخه کوتاه خبر', text)

    def test_short_verified_summary_preferred_to_cutting_a_long_full_summary(self):
        text = caption(dict(STORY, full_summary_fa=(BODY + ' ') * 45), 'crypto', extra_credits=CREDITS)
        self.assertIn(TITLE + '\n\n' + BODY + '\n\n', text)
        self.assertLessEqual(len(text), 2200)

    def test_long_summary_uses_complete_sentences_without_cutting_credits(self):
        sentence = 'این جمله کامل فارسی برای بررسی محدودیت تعداد نویسه‌ها در کپشن نوشته شده است.'
        text = caption(dict(STORY, summary_fa=(sentence + ' ') * 70), 'crypto', extra_credits=CREDITS)
        body = text.split('\n\n', 2)[1]
        self.assertTrue(body.endswith('.'))
        self.assertTrue(((sentence + ' ') * 70).startswith(body))
        self.assertLessEqual(len(text), 2200)
        for credit in CREDITS: self.assertIn(credit, text)

    def test_single_long_sentence_gets_a_visible_whole_word_excerpt(self):
        value = ' '.join('واژه' + str(i) for i in range(150))
        result = summary(dict(STORY, summary_fa=value), 121)
        self.assertTrue(result.endswith('…'))
        self.assertLessEqual(len(result), 121)
        self.assertIn(result[:-1].split()[-1], value.split())
        self.assertTrue(value.startswith(result[:-1] + ' '))

    def test_decimal_amounts_and_persian_sentence_ending_are_preserved(self):
        sentence = 'در این مثال آزمایشی، مقدار ۱.۲۳ به ۴.۵۶ تغییر کرده است.'
        result = summary(dict(STORY, summary_fa=sentence + ' ' + BODY * 20), len(sentence) + 3)
        self.assertEqual(result, sentence)
        question = 'آیا این متن نمونه درست است؟'
        self.assertEqual(summary(dict(STORY, summary_fa=question + ' ' + BODY * 20), len(question) + 2), question)

    def test_abbreviation_is_not_mistaken_for_a_complete_sentence(self):
        sentence = 'این نمونه با نام U.S. و یک عبارت فارسی ادامه پیدا می‌کند.'
        result = summary(dict(STORY, summary_fa=sentence + ' ' + BODY * 20), len(sentence) + 2)
        self.assertEqual(result, sentence)

    def test_required_credits_are_never_truncated_to_force_a_fit(self):
        credit = 'Music license: ' + ('x' * 2200)
        with self.assertRaises(CaptionError): caption(STORY, 'crypto', extra_credits=[credit])

    def test_trial_and_explicit_direct_both_include_news(self):
        for mode in ('trial', 'direct'):
            with self.subTest(mode=mode):
                text = caption(STORY, 'crypto', mode, extra_credits=CREDITS)
                self.assertTrue(text.startswith(TITLE + '\n\n' + BODY))
                self.assertEqual('به‌صورت Trial Reel' in text, mode == 'trial')

    def test_forecast_opinion_and_rss_scope_disclosures_remain(self):
        for story_type, label in (('forecast', 'پیش‌بینی کریپتو'), ('opinion', 'تحلیل کریپتو'),
                                  ('promotional', 'محتوای معرفی')):
            text = caption(dict(STORY, story_type=story_type, source_scope='coindesk_rss_summary'), 'crypto')
            self.assertIn(label, text)
            self.assertIn('فید رسمی کوین‌دسک', text)
            self.assertGreater(text.index('فید رسمی کوین‌دسک'), text.index(BODY))

    def test_existing_asset_selection_draft_budget_is_unchanged(self):
        expected = 'صرافی کیانی | خبر کریپتو\n\n' + TITLE + '\n\nمنبع: Example Publisher\nhttps://publisher.example/news\n\nاین ویدئو به‌صورت Trial Reel منتشر شده است.'
        self.assertEqual(caption(STORY, 'crypto', include_summary=False), expected)
        rss = dict(STORY, source_scope='coindesk_rss_summary', full_summary_fa=BODY + ' متن بیشتر.')
        expected = expected.replace('\n\nاین ویدئو به‌صورت Trial Reel', '\n\nاین ویدئو بر اساس عنوان و خلاصه فید رسمی کوین‌دسک تهیه شده است.\n\nنسخه کوتاه خبر\n\nاین ویدئو به‌صورت Trial Reel')
        self.assertEqual(caption(rss, 'crypto', include_summary=False), expected)

    def test_same_full_summary_is_not_repeated(self):
        text = caption(dict(STORY, full_summary_fa=BODY), 'crypto', extra_credits=CREDITS)
        self.assertEqual(text.count(BODY), 1)

    def test_empty_news_is_rejected_instead_of_publishing_credit_only(self):
        with self.assertRaises(CaptionError): caption(dict(STORY, summary_fa=''), 'crypto')

    def test_final_caption_is_assembled_before_paid_narration_and_meta_container(self):
        create = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'create_reel')
        calls = [n for n in ast.walk(create) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        final = [n for n in calls if n.func.id == '_caption' and any(k.arg == 'extra_credits' for k in n.keywords)]
        self.assertEqual(len(final), 1)
        for name in ('_prepare_narration', 'container_fields'):
            self.assertLess(final[0].lineno, min(n.lineno for n in calls if n.func.id == name))


if __name__ == '__main__': unittest.main()
