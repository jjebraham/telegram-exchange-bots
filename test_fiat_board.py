import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import instagram_carousel as carousel
import instagram_daily_rates as rates_app


class CurrencyBoardTests(unittest.TestCase):
    def setUp(self):
        self.rates, self.sections = carousel.sample_bundle()

    def test_complete_order_and_values(self):
        rows, observed = carousel.currency_board(self.sections)
        original = next(section for section in self.sections if section['kind'] == 'fx')
        self.assertEqual([row['code'] for row in rows], list(carousel.FX_NAMES))
        self.assertEqual({r['code']: r['price'] for r in rows},
                         {r['code']: r['price'] for r in original['rows']})
        self.assertIsNotNone(observed.utcoffset())

    def test_missing_duplicate_bad_and_fractional_rates_are_rejected(self):
        with self.assertRaises(carousel.CarouselError):
            carousel.currency_board([])
        for case in ('missing', 'duplicate', 'invalid', 'fractional', 'no_timezone'):
            sections = copy.deepcopy(self.sections)
            fx = next(section for section in sections if section['kind'] == 'fx')
            if case == 'missing':
                fx['rows'].pop()
            elif case == 'duplicate':
                fx['rows'][1]['code'] = fx['rows'][0]['code']
            elif case == 'invalid':
                fx['rows'][0]['price'] = '-10'
            elif case == 'fractional':
                fx['rows'][0]['price'] = '1.4'
            else:
                fx['generated_at'] = '2026-10-09T13:00:00'
            with self.subTest(case=case), self.assertRaises(carousel.CarouselError):
                carousel.currency_board(sections)

    def test_old_fx_is_not_fresh_for_publication(self):
        fx = copy.deepcopy(next(section for section in self.sections if section['kind'] == 'fx'))
        fx['generated_at'] = (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        with self.assertRaises(carousel.CarouselError):
            carousel.assert_fresh_sections([fx])

    def test_eight_slide_sample_preserves_original_customer_and_sections(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            paths, caption = carousel.render_carousel(rates_app, self.rates, self.sections, now, Path(tmp), sample=True)
            self.assertEqual(len(paths), 8)
            self.assertTrue(all(path.is_file() and path.stat().st_size > 10000 for path in paths))
            manifest_path = next(Path(tmp).glob('*.json'))
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['slides'], [str(path) for path in paths])
            self.assertEqual(manifest['sections'], self.sections)
            self.assertEqual(manifest['customer_rates'], {k: str(v) for k, v in self.rates.items()})
            self.assertTrue(manifest['sample'])
            self.assertIn('اسلاید اول: نرخ ارز بازار آزاد ایران', caption)


if __name__ == '__main__':
    unittest.main()
