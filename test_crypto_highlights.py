import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import instagram_top50_renderer as renderer
import instagram_top50_prices as app
from crypto_top50_data import PricesError, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(os.environ.get('TOP50_TEST_SNAPSHOT', ROOT/'sample-snapshot.json'))
ASSETS = Path(os.environ.get('TOP50_TEST_ASSETS', ROOT/'assets'))
HAVE_PREVIEW = FIXTURE.is_file() and (ASSETS/'fonts/Vazirmatn-Bold.ttf').is_file()


class HighlightsTests(unittest.TestCase):
    def test_breadth_states_and_no_fake_flat_for_missing_data(self):
        cases = [(['1']*32+['-1']*16+['0']*2, 'green', 32, 16, 2, 0),
                 (['-1']*34+['1']*14+['0']*2, 'red', 14, 34, 2, 0),
                 (['1']*24+['-1']*24+['0']*2, 'mixed', 24, 24, 2, 0),
                 (['0']*50, 'flat', 0, 0, 50, 0),
                 ([None]*50, 'missing', 0, 0, 0, 50),
                 (['1']*10+['-1']*9+['0']*31, 'mixed', 10, 9, 31, 0)]
        for values, state, up, down, flat, missing in cases:
            with self.subTest(state=state, up=up):
                result = renderer.breadth({'coins': [{'change_24h': x} for x in values]})
                self.assertEqual(result, dict(state=state, up=up, down=down, flat=flat,
                                             missing=missing, known=50-missing, total=50))

    def test_partial_data_uses_available_denominator(self):
        result = renderer.breadth({'coins': [{'change_24h': x} for x in ['1']*25+['-1']*20+[None]*5]})
        self.assertEqual(result['known'], 45)
        self.assertEqual(result['missing'], 5)
        self.assertEqual(result['flat'], 0)
        self.assertEqual(result['state'], 'green')

    def test_gain_threshold_preserves_existing_visible_two_percent_rule(self):
        rows = [{'change_24h': x} for x in ['9.1', '5', '4', '3', '2.005', '2.004', '2', '1']]
        self.assertEqual([x['change_24h'] for x in renderer.significant_gainers({'gainers': rows})],
                         ['9.1', '5', '4', '3', '2.005'])
        self.assertEqual(renderer.significant_gainers({'gainers': rows[5:]}), [])

    @unittest.skipUnless(HAVE_PREVIEW, 'Optional preview fixture and brand assets not supplied')
    def test_local_calendar_and_movement_display(self):
        local = datetime(2026, 11, 9, 16, tzinfo=renderer.ZoneInfo('Europe/Istanbul'))
        self.assertEqual(renderer.calendar_badge(local, ASSETS), 'دوشنبه 18 آبان')
        self.assertEqual(renderer.move(None), ('—', renderer.NEUTRAL))
        self.assertEqual(renderer.move('-0.0001'), ('0.00%', renderer.NEUTRAL))
        self.assertEqual(renderer.move('1.205'), ('+1.21%', renderer.GREEN))

    @unittest.skipUnless(HAVE_PREVIEW, 'Optional preview fixture and brand assets not supplied')
    def test_render_preserves_snapshot_and_has_four_full_size_slides(self):
        original = json.loads(FIXTURE.read_text(encoding='utf-8'))
        before = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as temp:
            paths = renderer.render(original, temp, ASSETS)
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(str(p).endswith(f'-{i:02}.jpg') for i, p in enumerate(paths, 1)))
            for path in paths:
                with Image.open(path) as image:
                    self.assertEqual(image.size, (1080, 1350))
                    self.assertGreater(path.stat().st_size, 30000)
        self.assertEqual(original, before)

    @unittest.skipUnless(HAVE_PREVIEW, 'Optional preview fixture and brand assets not supplied')
    def test_sample_is_still_forbidden_for_real_publication(self):
        snapshot = json.loads(FIXTURE.read_text(encoding='utf-8'))
        with self.assertRaisesRegex(PricesError, 'sample snapshot cannot be published'):
            validate_snapshot(snapshot, publishing=True)

    @unittest.skipUnless(HAVE_PREVIEW, 'Optional preview fixture and brand assets not supplied')
    def test_no_qualifiers_are_not_filled_with_invented_coins(self):
        with tempfile.TemporaryDirectory() as temp:
            card = renderer.Card(ASSETS, renderer.GREEN_THEME, renderer.brand_logo(ASSETS), sample=True)
            with patch.object(card, 'text', wraps=card.text) as text:
                renderer.movers(card, [])
            strings = [str(call.args[0]) for call in text.call_args_list]
            self.assertIn('امروز ارزی با این شرایط پیدا نشد', strings)
            self.assertFalse(any('%' in x for x in strings))

    @unittest.skipUnless(HAVE_PREVIEW, 'Optional preview fixture and brand assets not supplied')
    def test_missing_data_is_shown_explicitly_in_cover_and_caption(self):
        snapshot = json.loads(FIXTURE.read_text(encoding='utf-8'))
        for coin in snapshot['coins']:
            coin['change_24h'] = None
        card = renderer.Card(ASSETS, renderer.GREEN_THEME, renderer.brand_logo(ASSETS), sample=True)
        with patch.object(card, 'text', wraps=card.text) as text:
            renderer.cover(card, snapshot, renderer.breadth(snapshot))
        strings = [str(call.args[0]) for call in text.call_args_list]
        self.assertIn('داده‌ها کامل نیست', strings)
        self.assertIn('دایره توخالی: 50 ارز بدون داده تغییرات', strings)
        caption = renderer.caption(snapshot)
        self.assertIn('برای 50 ارز، داده تغییر ۲۴ ساعته در دسترس نیست', caption)
        self.assertIn('https://coinpaprika.com', caption)
        self.assertIn('https://t.me/kianiexchangebot', caption)
        self.assertLessEqual(len(caption), 2200)
        self.assertNotIn('۱۲ اسلاید', caption)
        self.assertNotIn('قیمت تومان =', caption)


FAKE_HELPER = '''
from urllib.parse import urlsplit
events = []
def verify_public_image(url): events.append(('verify',url))
def _create_container(payload):
    events.append(('create',payload))
    return 'parent' if payload.get('media_type')=='CAROUSEL' else urlsplit(payload['image_url']).path.rsplit('/',1)[-1]
def _wait_for_container(child): pass
def _publish_container(parent):
    events.append(('publish',parent))
    return 'fake-media'
'''


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'instagram_daily_rates.py').write_text(FAKE_HELPER, encoding='utf-8')
        self.con = app.database(self.root/'preview.sqlite3')
        self.now = datetime.now(timezone.utc)
        self.snapshot = {'generated_at': self.now.isoformat()}
        self.day = self.now.astimezone(renderer.ZoneInfo('Europe/Istanbul')).date().isoformat()
        self.con.execute('INSERT INTO top50_snapshots VALUES (?,?,?,?,?)', ('fixture', self.day, 0, '{}', '{}'))
        self.con.commit()
        self.manifest = dict(snapshot_id='fixture', images=[f'slide-{i}.jpg' for i in range(1,5)],
                             sections=list(renderer.SECTIONS), caption='Sample')
        self.patches = [patch.object(app, 'validate_snapshot'), patch.object(app, 'log_stage'),
                        patch.dict(os.environ, {'INSTAGRAM_USER_ID':'fake','INSTAGRAM_ACCESS_TOKEN':'fake'})]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.con.close()
        self.temp.cleanup()

    def test_four_slides_keep_order_and_do_not_publish_twice(self):
        self.assertEqual(app.publish(self.con,self.snapshot,self.manifest,self.root,'https://example.com'),'fake-media')
        helper = sys.modules['kiani_top50_shared_publisher']
        parents = [value for kind,value in helper.events if kind=='create' and value.get('media_type')=='CAROUSEL']
        self.assertEqual(parents[0]['children'], 'slide-1.jpg,slide-2.jpg,slide-3.jpg,slide-4.jpg')
        self.assertEqual(len([1 for kind,value in helper.events if kind=='publish']),1)
        self.assertIsNone(app.publish(self.con,self.snapshot,self.manifest,self.root,'https://example.com'))
        self.assertEqual(len([1 for kind,value in helper.events if kind=='publish']),1)

    def test_old_twelve_slide_manifest_and_wrong_order_are_rejected_before_requests(self):
        for images, sections in [(list(range(12)), ['market_pulse','declines']+['top50']*10),
                                 (self.manifest['images'], ['market_pulse','declines','gainers','engagement'])]:
            manifest = dict(self.manifest, images=[str(x) for x in images], sections=sections)
            with self.assertRaisesRegex(PricesError, 'Exactly four ordered slides'):
                app.publish(self.con,self.snapshot,manifest,self.root,'https://example.com')
            helper = sys.modules['kiani_top50_shared_publisher']
            self.assertEqual(helper.events, [])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM top50_publications').fetchone()[0],0)

    def test_uncertain_existing_publication_prevents_retry(self):
        self.con.execute("INSERT INTO top50_publications(day,snapshot_id,status,started_at,manifest_json) VALUES (?,?,'needs_review',0,'{}')",(self.day,'fixture'))
        self.con.commit()
        with self.assertRaisesRegex(PricesError, 'uncertain result'):
            app.publish(self.con,self.snapshot,self.manifest,self.root,'https://example.com')


if __name__ == '__main__':
    unittest.main()
