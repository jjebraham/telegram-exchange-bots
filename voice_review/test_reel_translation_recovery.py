from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
usage = types.ModuleType('instagram_reel_usage')
usage.tracked = lambda *args, **kwargs: lambda function: function
sys.modules.setdefault('instagram_reel_usage', usage)

import economy_news_translation as translation
from instagram_crypto_news import NewsError
import instagram_trial_reels as trial
import instagram_manual_news_intake as intake


class NumericRepairTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE economy_translation_cache(input_hash TEXT PRIMARY KEY,model TEXT,title_fa TEXT,summary_fa TEXT,created_at REAL)')
        self.material = dict(title_original='Company shares rise', source_text='Shares rose 2.70% after the announcement.',
            article_date='2026-11-09', source_name='Example', source_url='https://example.com/shares')

    def tearDown(self):
        self.con.close()

    def result(self, number):
        return dict(headline_fa='رشد سهام شرکت پس از اعلام خبر تازه',
            summary_fa='سهام شرکت پس از انتشار خبر تازه ' + number + ' درصد رشد کرد. گزارش به واکنش بازار اشاره دارد و درباره ادامه این روند نتیجه قطعی ارائه نمی‌کند.')

    def test_equivalent_decimal_digit_and_group_formats_are_exact_not_rounded(self):
        for left, right in [('2.70','۲٫۷'),('0.50','٠٫٥'),('1,000.00','۱٬۰۰۰'),('0.5','.50')]:
            self.assertEqual(translation.numbers(left), translation.numbers(right))
        self.assertNotEqual(translation.numbers('0.1'), translation.numbers('0.100000000000000000000000000001'))
        self.assertNotEqual(translation.numbers('123456789012345678901234567890123456789'), translation.numbers('123456789012345678901234567890123456788'))
        self.assertNotEqual(translation.numbers('1.3'), translation.numbers('1300'))

    def test_equivalent_number_passes_but_invented_and_scaled_values_are_rejected(self):
        translation.validate_translation(self.result('۲٫۷۰'), self.material['source_text'])
        for value in ('۲٫۷۱', '۲۷۰', '۹۹'):
            with self.assertRaises(translation.TranslationNumberError) as raised:
                translation.validate_translation(self.result(value), self.material['source_text'])
            self.assertTrue(raised.exception.unsupported_numbers)

    def test_only_valid_thousands_grouping_is_removed(self):
        self.assertEqual(translation.numbers('1,300,000'), translation.numbers('۱۳۰۰۰۰۰'))
        self.assertEqual(translation.numbers('1,30,000'), translation.numbers('۱۳۰۰۰۰'))
        self.assertNotEqual(translation.numbers('12'), translation.numbers('1,2'))
        self.assertNotEqual(translation.numbers('2.70'), translation.numbers('2,70'))
        self.assertNotEqual(translation.numbers('1.23'), translation.numbers('1.2,3'))

    def test_one_numeric_correction_includes_specific_feedback_and_only_caches_valid_output(self):
        seen = []
        def request(body):
            seen.append(body)
            return json.dumps(self.result('۹۹' if len(seen) == 1 else '۲٫۷'))
        title, summary = translation.translate(self.con, self.material, request_fn=request)
        self.assertIn('۲٫۷', summary)
        self.assertEqual(len(seen), 2)
        feedback = seen[1]['messages'][-1]['content']
        self.assertIn('99', feedback)
        self.assertIn('Do not round, convert units', feedback)
        rejected = self.con.execute('SELECT unsupported_json,source_url FROM translation_number_rejections').fetchall()
        self.assertEqual(json.loads(rejected[0][0]), ['99'])
        self.assertEqual(rejected[0][1], self.material['source_url'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM economy_translation_cache').fetchone()[0], 1)
        self.assertEqual(translation.translate(self.con, self.material, request_fn=lambda body: self.fail('No recharge')), (title, summary))

    def test_exhausted_numeric_repair_is_not_repeated_by_admin_wrapper(self):
        request = Mock(return_value=json.dumps(self.result('۹۹')))
        ranked = types.SimpleNamespace(translate=lambda con, row: translation.translate(con, row, request_fn=request))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(translation.TranslationNumberError) as raised:
            intake.translate_admin_news(ranked, self.con, self.material)
        self.assertTrue(raised.exception.translation_retry_exhausted)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM economy_translation_cache').fetchone()[0], 0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM translation_number_rejections').fetchone()[0], 2)

    def test_transport_failure_is_not_blindly_retried_or_recorded_as_bad_numbers(self):
        request = Mock(side_effect=NewsError('DeepSeek translation request failed (HTTP 503).'))
        with self.assertRaises(NewsError):
            translation.translate(self.con, self.material, request_fn=request)
        self.assertEqual(request.call_count, 1)
        self.assertIsNone(self.con.execute("SELECT name FROM sqlite_master WHERE name='translation_number_rejections'").fetchone())

    def test_bad_length_after_numeric_repair_does_not_start_another_admin_retry_chain(self):
        responses = [json.dumps(self.result('۹۹')), json.dumps(dict(headline_fa='عنوان معتبر فارسی', summary_fa='کوتاه'))]
        request = Mock(side_effect=responses)
        ranked = types.SimpleNamespace(translate=lambda con, row: translation.translate(con, row, request_fn=request))
        with self.assertRaises(NewsError) as raised:
            intake.translate_admin_news(ranked, self.con, self.material)
        self.assertTrue(raised.exception.translation_retry_exhausted)
        self.assertEqual(request.call_count, 2)


class CandidateRecoveryTests(unittest.TestCase):
    def candidates(self, count=2):
        return [('crypto' if i % 2 == 0 else 'economy', dict(source_url='https://example.com/' + str(i),
            trial_score=100-i, article_published_at=1000, title_original='News ' + str(i))) for i in range(count)]

    @contextmanager
    def database(self, path):
        yield object()

    def ranked(self):
        return types.SimpleNamespace(SOURCES={'crypto':'crypto-db','economy':'economy-db'}, configure_engine=Mock())

    def test_next_verified_candidate_is_used_after_rejected_translation(self):
        record = Mock()
        candidates = self.candidates()
        duplicate = ('economy', dict(candidates[0][1], trial_score=99.5))
        with patch.object(trial, 'translate_scheduled_news', side_effect=[translation.TranslationNumberError({'99'}, {'2.7'}), ('عنوان', 'خلاصه')]) as prepare:
            result = trial.choose_scheduled_translation(candidates + [duplicate], self.ranked(), self.database, record=record)
        self.assertEqual(result[:2], candidates[1])
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual([call.args[3] for call in record.call_args_list], ['rejected','prepared'])
        self.assertEqual(record.call_args_list[0].args[4], 'unverified_number')

    def test_extra_main_story_checks_only_happen_after_initial_winners_fail(self):
        refill = Mock(return_value=self.candidates(3)[2:])
        with patch.object(trial, 'translate_scheduled_news', return_value=('عنوان', 'خلاصه')):
            trial.choose_scheduled_translation(self.candidates(), self.ranked(), self.database, refill=refill)
        refill.assert_not_called()
        with patch.object(trial, 'translate_scheduled_news', side_effect=[
                translation.TranslationNumberError({'99'}, {'2.7'}),
                translation.TranslationNumberError({'99'}, {'2.7'}), ('عنوان', 'خلاصه')]) as prepare:
            result = trial.choose_scheduled_translation(self.candidates(), self.ranked(), self.database, refill=refill)
        self.assertEqual(result[1]['source_url'], 'https://example.com/2')
        self.assertEqual(prepare.call_count, 3)
        self.assertEqual(refill.call_count, 1)

    def test_attempt_budget_stops_after_three_rejections(self):
        with patch.object(trial, 'translate_scheduled_news', side_effect=translation.TranslationNumberError({'99'}, {'2.7'})) as prepare:
            with self.assertRaisesRegex(trial.TrialReelError, 'No scheduled candidate passed'):
                trial.choose_scheduled_translation(self.candidates(5), self.ranked(), self.database)
        self.assertEqual(prepare.call_count, 3)

    def test_one_available_category_can_refill_to_third_candidate_without_looping(self):
        candidates = self.candidates(3)
        refill = Mock(side_effect=[[candidates[1]], [candidates[2]]])
        with patch.object(trial, 'translate_scheduled_news', side_effect=[
                translation.TranslationNumberError({'99'}, {'2.7'}),
                translation.TranslationNumberError({'99'}, {'2.7'}), ('عنوان', 'خلاصه')]):
            result = trial.choose_scheduled_translation(candidates[:1], self.ranked(), self.database, refill=refill)
        self.assertEqual(result[1]['source_url'], candidates[2][1]['source_url'])
        self.assertEqual(refill.call_count, 2)
        refill = Mock(return_value=candidates[:1])
        with patch.object(trial, 'translate_scheduled_news', side_effect=translation.TranslationNumberError({'99'}, {'2.7'})):
            with self.assertRaises(trial.TrialReelError):
                trial.choose_scheduled_translation(candidates[:1], self.ranked(), self.database, refill=refill)
        self.assertEqual(refill.call_count, 1)

    def test_service_failure_aborts_without_trying_another_paid_candidate(self):
        with patch.object(trial, 'translate_scheduled_news', side_effect=NewsError('DeepSeek translation request failed (HTTP 503).')) as prepare:
            with self.assertRaises(NewsError):
                trial.choose_scheduled_translation(self.candidates(), self.ranked(), self.database)
        self.assertEqual(prepare.call_count, 1)

    def test_attempt_diagnostics_persist_and_never_change_slot_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            db = state / 'reels.sqlite3'
            with patch.object(trial, 'STATE', state), patch.object(trial, 'DB', db):
                trial.record_scheduled_translation('2026-11-09', '15:00', 1, 'crypto', self.candidates()[0][1], 'rejected', 'unverified_number', ('99',))
                with closing(trial._connect()) as con:
                    row = con.execute('SELECT status,error_code,unsupported_json FROM scheduled_translation_attempts').fetchone()
                    self.assertEqual(tuple(row), ('rejected','unverified_number','["99"]'))
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM scheduled_runs').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
