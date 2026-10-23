"""Offline checks of the approved template and explicitly authorized manual test."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'deploy/instagram-iran-gold'))

from PIL import Image
import instagram_iran_gold as app
import instagram_iran_gold_renderer as renderer
from iran_gold_data import GoldError
from test_iran_gold_servix import snapshot, NOW

ADMIN = runpy.run_path(str(ROOT / 'deploy/instagram-iran-gold/activate_template.py'))
DAY = NOW.astimezone(app.TEHRAN).date().isoformat()
KEY = DAY + ':' + renderer.TEMPLATE_VERSION


def board():
    value = snapshot()
    for row in value['rows']:
        row.update(day=None, month=None)
    return value


class TemplateChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.con = app.database(self.root / 'gold.sqlite3')
        self.value = board()
        self.manifest = dict(image_urls=['https://peerexo.com/instagram-rates/iran-gold/test.jpg'],
            images=['/var/www/peerexo.com/public/instagram-rates/iran-gold/test.jpg'],
            caption='synthetic fixture', template_version=renderer.TEMPLATE_VERSION,
            publication_mode='owner_requested_template_test')

    def tearDown(self):
        self.con.close()
        self.directory.cleanup()

    def original(self, status='published'):
        self.con.execute('INSERT INTO instagram_news_publications(day,status,started_at,media_id,manifest_json) VALUES (?,?,0,?,?)',
            (DAY, status, '123', '{}'))
        self.con.execute('INSERT INTO gold_history VALUES (?,?,?,?)',
            (DAY, self.value['generated_at'], json.dumps({r['id']: r['price'] for r in self.value['rows']}), '123'))
        self.con.commit()

    def publish_test(self, graph):
        with patch('instagram_iran_gold.validate'), patch('instagram_iran_gold.helper', return_value=graph), \
                patch.dict(os.environ, INSTAGRAM_USER_ID='999', INSTAGRAM_ACCESS_TOKEN='SYNTHETIC_ONLY'), \
                redirect_stdout(io.StringIO()):
            app.publish(self.con, self.value, self.manifest, self.root,
                authorized_day=DAY, template_test=True)

    def graph(self):
        graph = MagicMock()
        graph._create_container.return_value = '456'
        graph._publish_container.return_value = '789'
        return graph

    def test_daily_key_is_unchanged(self):
        self.assertEqual(app.publication_key(self.con, DAY), DAY)

    def test_test_key_is_stable_and_separate(self):
        self.original()
        self.assertEqual(app.publication_key(self.con, DAY, True), KEY)

    def test_uncertain_daily_blocks_test(self):
        self.original('needs_review')
        with self.assertRaises(GoldError): app.publication_key(self.con, DAY, True)

    def test_test_needs_explicit_date(self):
        with self.assertRaises(GoldError):
            app.publish(self.con, self.value, self.manifest, self.root, template_test=True)

    def test_test_needs_reviewed_version(self):
        self.manifest['template_version'] = 'unknown'
        with self.assertRaises(GoldError):
            app.publish(self.con, self.value, self.manifest, self.root, authorized_day=DAY, template_test=True)

    def test_original_and_comparison_history_are_preserved(self):
        self.original()
        before = [tuple(r) for r in self.con.execute('SELECT * FROM gold_history')]
        graph = self.graph()
        self.publish_test(graph)
        self.assertEqual(self.con.execute('SELECT media_id FROM instagram_news_publications WHERE day=?', (DAY,)).fetchone()[0], '123')
        test = self.con.execute('SELECT * FROM instagram_news_publications WHERE day=?', (KEY,)).fetchone()
        self.assertEqual((test['status'], test['media_id']), ('published', '789'))
        self.assertEqual([tuple(r) for r in self.con.execute('SELECT * FROM gold_history')], before)
        graph._publish_container.assert_called_once_with('456')

    def test_repeated_test_does_not_contact_meta(self):
        self.publish_test(self.graph())
        graph = self.graph()
        self.publish_test(graph)
        graph._create_container.assert_not_called()
        graph._publish_container.assert_not_called()

    def test_daily_still_blocks_second_regular_post(self):
        self.original()
        with patch('instagram_iran_gold.validate'), patch('instagram_iran_gold.helper') as graph:
            app.publish(self.con, self.value, self.manifest, self.root, authorized_day=DAY)
            graph.assert_not_called()

    def test_expired_collection_never_reaches_final_publish(self):
        graph = self.graph()
        with patch('instagram_iran_gold.validate', side_effect=[None, GoldError('expired')]), \
                patch('instagram_iran_gold.helper', return_value=graph), \
                patch.dict(os.environ, INSTAGRAM_USER_ID='999', INSTAGRAM_ACCESS_TOKEN='SYNTHETIC_ONLY'):
            with self.assertRaises(GoldError):
                app.publish(self.con, self.value, self.manifest, self.root, authorized_day=DAY, template_test=True)
        graph._publish_container.assert_not_called()

    def test_uncertain_test_blocks_retries(self):
        graph = self.graph()
        graph._publish_container.side_effect = TimeoutError('synthetic')
        with self.assertRaises(TimeoutError): self.publish_test(graph)
        self.assertEqual(self.con.execute('SELECT status FROM instagram_news_publications WHERE day=?', (KEY,)).fetchone()[0], 'needs_review')
        with self.assertRaises(GoldError): self.publish_test(self.graph())

    def test_test_appears_in_existing_story_and_insights_adapter_query(self):
        self.publish_test(self.graph())
        rows = self.con.execute("SELECT media_id,manifest_json FROM instagram_news_publications WHERE status='published' AND finished_at>=0").fetchall()
        self.assertEqual(rows[0]['media_id'], '789')
        self.assertEqual(json.loads(rows[0]['manifest_json'])['images'], self.manifest['images'])

    def test_renderer_uses_supplied_transparent_icons(self):
        icons = renderer.icons()
        self.assertEqual([x.size for x in icons], [(52, 52), (52, 52)])
        self.assertTrue(all(x.mode == 'RGBA' and x.getpixel((0, 0))[3] == 0 for x in icons))
        self.assertTrue(all(name in app.FILES for name in renderer.ICON_FILES))

    def test_both_section_bars_fit(self):
        self.assertEqual(renderer.row_y(0), 540)
        self.assertEqual(renderer.row_y(5) - (renderer.row_y(4)+68), 56)
        self.assertLess(renderer.row_y(6)+68, 1170)

    def test_caption_has_tehran_market_and_no_removed_sentence(self):
        assets = Path(os.getenv('KIANI_GOLD_TEST_ASSETS', str(Path.home() / 'kiani-instagram-publisher')))
        text = renderer.caption(self.value, assets)
        self.assertIn('بازار تهران', text)
        self.assertNotIn('سابقه', text)
        self.assertNotIn('Alanchand', text)
        self.assertLessEqual(len(text), 2200)

    def test_render_is_1080_by_1350_and_preserves_values(self):
        assets = Path(os.getenv('KIANI_GOLD_TEST_ASSETS', str(Path.home() / 'kiani-instagram-publisher')))
        before = deepcopy(self.value)
        paths = renderer.render(self.value, self.root, assets, preview=True)
        with Image.open(paths[0]) as image:
            self.assertEqual(image.size, (1080, 1350))
        self.assertEqual(before, self.value)

    def test_synthetic_layout_cannot_be_published(self):
        self.value['layout_sample'] = True
        with self.assertRaises(ValueError): renderer.render(self.value, self.root, self.root)

    def test_manual_flag_never_enters_daily_launcher(self):
        from activate_servix import wrapper
        text = wrapper(Path('/fixture'), 'a'*40)
        self.assertIn(b' --publish\n', text)
        self.assertNotIn(b'--template-test-on', text)

    def test_admin_rejects_wrong_day_without_launch(self):
        clock = MagicMock()
        clock.now.return_value = NOW.astimezone(app.TEHRAN)
        fn = ADMIN['post_test']
        with patch.dict(fn.__globals__, datetime=clock), patch('subprocess.run') as launch:
            with self.assertRaises(RuntimeError): fn(self.root, ROOT, 'a'*40, '2026-10-24')
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=1)
