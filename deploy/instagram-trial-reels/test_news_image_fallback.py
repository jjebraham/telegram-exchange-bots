"""Offline tests for automatic carousel image fallback."""
import ast
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import uuid


SOURCE = Path(__file__).with_name('automatic_ranked_news_images.py')
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == 'prepare_first_with_images')
run = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
           and node.name == 'run')


class NewsError(Exception):
    pass


class NewsImageUnavailable(NewsError):
    pass


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [{'id': str(i)} for i in range(5)]
        self.audit = {}
        self.calls = []
        self.select_calls = []
        self.slot_is_open = True
        self.scope = {
            'MAIN_STORY_CHECK_LIMIT': 40,
            'NewsError': NewsError,
            'NewsImageUnavailable': NewsImageUnavailable,
            'time': time,
            'slot_open': lambda *args: self.slot_is_open,
            'select_main_stories': self.select,
            'prepare': self.prepare,
        }
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SOURCE), 'exec'), self.scope)
        self.behavior = {}

    def select(self, con, candidates, kind, limit, now, audit, checkpoint):
        self.select_calls.append([row['id'] for row in candidates])
        return candidates[:1]

    def prepare(self, con, row, kind, output, assets):
        self.calls.append(row['id'])
        error = self.behavior.get(row['id'])
        if error:
            raise error
        return ('saved', ['cover', 'second'], 'caption', {})

    def run_fallback(self, candidates=None):
        return self.scope['prepare_first_with_images'](
            None, self.candidates if candidates is None else candidates,
            'crypto', time.time(), self.audit, lambda: None,
            Path('.'), Path('.'), True, 'hour-10')

    def test_missing_images_tries_next_story_and_preserves_order(self):
        self.behavior['0'] = NewsImageUnavailable('two images unavailable')
        selected, prepared = self.run_fallback()
        self.assertEqual([row['id'] for row in selected], ['1'])
        self.assertEqual(self.calls, ['0', '1'])
        self.assertEqual(self.select_calls[1], ['1', '2', '3', '4'])
        self.assertEqual(len(prepared[0][1]), 2)
        self.assertEqual([a['status'] for a in self.audit['image_selection_attempts']],
                         ['missing_required_images', 'prepared'])

    def test_no_more_than_three_image_failures(self):
        self.behavior = {str(i): NewsImageUnavailable() for i in range(5)}
        self.assertEqual(self.run_fallback(), ([], []))
        self.assertEqual(self.calls, ['0', '1', '2'])

    def test_other_errors_stop_without_trying_another_story(self):
        self.behavior['0'] = NewsError('translation failed')
        with self.assertRaisesRegex(NewsError, 'translation failed'):
            self.run_fallback()
        self.assertEqual(self.calls, ['0'])

    def test_expired_slot_does_not_start_a_candidate(self):
        self.slot_is_open = False
        with self.assertRaisesRegex(NewsError, 'slot expired'):
            self.run_fallback()
        self.assertEqual(self.calls, [])

    def test_slot_expiring_after_image_failure_stops_retry(self):
        def prepare_then_expire(con, row, kind, output, assets):
            self.calls.append(row['id'])
            self.slot_is_open = False
            raise NewsImageUnavailable()
        self.scope['prepare'] = prepare_then_expire
        with self.assertRaisesRegex(NewsError, 'slot expired'):
            self.run_fallback()
        self.assertEqual(self.calls, ['0'])

    def test_retry_skips_candidates_rejected_by_main_story_check(self):
        def select(con, candidates, kind, limit, now, audit, checkpoint):
            return [row for row in candidates if row['id'] != '0'][:1]
        self.scope['select_main_stories'] = select
        self.behavior['1'] = NewsImageUnavailable()
        selected, _ = self.run_fallback()
        self.assertEqual(self.calls, ['1', '2'])
        self.assertEqual(selected[0]['id'], '2')

    def test_no_eligible_story_produces_no_post(self):
        self.assertEqual(self.run_fallback([]), ([], []))
        self.assertEqual(self.calls, [])

    def test_preview_runs_fallback_and_records_the_success(self):
        self.behavior['0'] = NewsImageUnavailable()
        self.integration_preview(expected='previewed', expected_calls=['0', '1'])

    def test_preview_records_all_image_failures_without_publishing(self):
        self.behavior = {str(i): NewsImageUnavailable() for i in range(5)}
        self.integration_preview(expected='no_usable_images', expected_calls=['0', '1', '2'])

    def integration_preview(self, expected, expected_calls):
        for row in self.candidates:
            row.update(title_original='news', trial_score=90, components={},
                       coverage_outlets=['source'],
                       assessment={k: {'reason': 'ok'} for k in ('impact', 'relevance', 'usefulness')})
        engine = types.SimpleNamespace(local_time=lambda now: 'now', ISTANBUL=timezone.utc,
                                       init_trial=lambda con: None,
                                       readonly=lambda path: nullcontext(object()))
        batch = types.ModuleType('instagram_news_batch')
        batch.plan = lambda publish: (10, {'remaining': 10})
        batch.guard = lambda: None
        self.scope.update({
            'engine': engine, 'datetime': datetime, 'uuid': uuid, 'Path': Path,
            'json': json, 'SOURCES': {'crypto': Path('unused')},
            'locks': lambda *args, **kwargs: nullcontext(),
            'database': lambda path: nullcontext(object()),
            'consumed': lambda *args: 0,
            'VERSION': 'test', 'runtime_fingerprint': lambda: 'test',
            'rank_events': lambda con, kind, now, checkpoint: (self.candidates, {}),
        })
        def prepare(con, row, kind, output, assets):
            self.calls.append(row['id'])
            if row['id'] in self.behavior:
                raise self.behavior[row['id']]
            return ('saved', [Path('cover.jpg'), Path('second.jpg')], 'caption', {})
        self.scope['prepare'] = prepare
        exec(compile(ast.Module(body=[run], type_ignores=[]), str(SOURCE), 'exec'), self.scope)
        with tempfile.TemporaryDirectory(prefix='fallback-preview-') as tmp:
            self.scope['STATE'] = Path(tmp)
            with patch.dict(sys.modules, {'instagram_news_batch': batch}):
                self.scope['run']('crypto', 'hour-10', False, Path(tmp))
            reports = list(Path(tmp).glob('runs/*/ranking.json'))
            self.assertEqual(len(reports), 1)
            audit = json.loads(reports[0].read_text(encoding='utf-8'))
        self.assertEqual(audit['status'], expected)
        self.assertEqual(self.calls, expected_calls)


if __name__ == '__main__':
    unittest.main()
