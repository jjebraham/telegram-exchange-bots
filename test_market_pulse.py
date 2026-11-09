import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import crypto_top50_data as data
import instagram_top50_renderer as renderer
import instagram_top50_prices as app


class MarketPulseTests(unittest.TestCase):
    def candidates(self):
        now = datetime.now(timezone.utc).isoformat()
        return [dict(id=f'coin-{i}', name=f'Coin {i}', symbol=f'C{i}', rank=i,
                     last_updated=now, quotes={'USD': dict(market_cap=str(1000000-i), price='1',
                         volume_24h='60000', percent_change_24h='0')}) for i in range(1, 101)]

    def test_losses_sorted_and_filters_applied(self):
        items = self.candidates()
        for i, value in enumerate(['-7', '-3.21', '-2.004', '-5', '-6', '-4', '-9']):
            items[i]['quotes']['USD']['percent_change_24h'] = value
        items[3]['quotes']['USD']['volume_24h'] = '50000'
        selected = data.select_decliners(items, {'coin-7'}, {'coin-5'}, datetime.now(timezone.utc))
        self.assertEqual([c['id'] for c in selected], ['coin-1', 'coin-6', 'coin-2'])

    def test_no_qualifiers_and_stale_excluded(self):
        items = self.candidates()
        items[0]['quotes']['USD']['percent_change_24h'] = '-15'
        items[0]['last_updated'] = '2001-01-01T00:00:00Z'
        self.assertEqual(data.select_decliners(items, set(), set(), datetime.now(timezone.utc)), [])
        self.assertEqual(len(data.select_decliners(items, set(), set(), datetime.now(timezone.utc), sample=True)), 1)

    def test_gain_threshold_and_top_five(self):
        snapshot = {'gainers': [{'change_24h': str(x)} for x in (8, 7, 6, 5, 4, 3, 2.004, 1)]}
        self.assertEqual([x['change_24h'] for x in renderer.significant_gainers(snapshot)], ['8', '7', '6', '5', '4'])
        self.assertEqual(renderer.significant_gainers({'gainers': [{'change_24h': '2.004'}]}), [])

    def test_four_highlights_keep_their_editorial_order(self):
        self.assertEqual(renderer.SECTIONS, ('market_pulse', 'gainers', 'declines', 'engagement'))

    def test_four_slide_publication_order_with_fake_meta(self):
        helper = '''\nfrom urllib.parse import urlsplit\nseen = []\ndef verify_public_image(url): pass\ndef _create_container(payload):\n    if payload.get('media_type') == 'CAROUSEL':\n        seen.append(payload['children'])\n        return 'parent'\n    return urlsplit(payload['image_url']).path.rsplit('/', 1)[-1]\ndef _wait_for_container(child): pass\ndef _publish_container(parent): return 'fake-media'\n'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'instagram_daily_rates.py').write_text(helper, encoding='utf-8')
            con = app.database(root / 'test.sqlite3')
            now = datetime.now(timezone.utc)
            snapshot = {'generated_at': now.isoformat()}
            manifest = {'snapshot_id': 'example', 'images': [f'slide-{i}.jpg' for i in range(1, 5)],
                        'sections': list(renderer.SECTIONS), 'caption': 'sample'}
            day = now.astimezone(app.ZoneInfo('Europe/Istanbul')).date().isoformat()
            con.execute('INSERT INTO top50_snapshots VALUES (?,?,?,?,?)', ('example', day, 0, '{}', '{}'))
            con.commit()
            with patch.object(app, 'validate_snapshot'), patch.object(app, 'log_stage'), \
                 patch.dict(os.environ, {'INSTAGRAM_USER_ID': 'fake', 'INSTAGRAM_ACCESS_TOKEN': 'fake'}):
                self.assertEqual(app.publish(con, snapshot, manifest, root, 'https://example.com'), 'fake-media')
            import sys
            helper_module = sys.modules['kiani_top50_shared_publisher']
            self.assertEqual(helper_module.seen, [','.join(f'slide-{i}.jpg' for i in range(1, 5))])
            self.assertEqual(con.execute('SELECT status FROM top50_publications').fetchone()[0], 'published')
            con.close()

    def test_renderer_four_and_missing_changes(self):
        fixture = Path(os.environ.get('TOP50_TEST_SNAPSHOT', 'missing-snapshot'))
        assets = Path(os.environ.get('TOP50_TEST_ASSETS', 'missing-assets'))
        if not fixture.is_file() or not assets.is_dir():
            self.skipTest('Optional private preview fixture and brand assets are unavailable')
        snapshot = json.loads(fixture.read_text(encoding='utf-8'))
        snapshot['sample'] = True
        with tempfile.TemporaryDirectory() as tmp:
            paths = renderer.render(snapshot, tmp, assets)
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(p.stat().st_size > 10000 for p in paths))
        snapshot['coins'][0]['change_24h'] = None
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(renderer.render(snapshot, tmp, assets)), 4)


if __name__ == '__main__':
    unittest.main()
