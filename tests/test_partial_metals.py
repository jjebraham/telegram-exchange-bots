"""Offline tests for a strictly verified gold-only global slide."""
from datetime import datetime, timezone
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import sys
import tempfile
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import global_metals_data as metals
import instagram_global_metals_renderer as renderer
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
import instagram_iran_gold as gold
sys.path.insert(0, str(ROOT/'deploy/instagram-price-recovery'))
import activate_recovery as activation


class PartialMetalsTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        stamp = self.now.isoformat()
        self.providers = {
            'servix': {'gold': {'price':'2000','updated_at':stamp}, 'silver':{'price':'50','updated_at':stamp}},
            'alanchand': {'gold': {'price':'2001','updated_at':stamp}, 'silver':{'price':'51.5','updated_at':stamp}},
            'dolarchand': {'gold': {'price':'2001','updated_at':stamp}, 'silver':{'price':'51.5','updated_at':stamp}},
        }
        self.validation = patch.object(metals, 'validate_quote', side_effect=lambda p,a,q,n: Decimal(q['price']))
        self.validation.start()

    def tearDown(self):
        self.validation.stop()

    def partial(self):
        return dict(schema_version=1,status='gold_only',generated_at=self.now.isoformat(),
                    providers=self.providers, rows=metals.assess(self.providers,self.now,gold_only=True), ratio=None)

    def test_gold_only_requires_gold_agreement_and_keeps_silver_absent(self):
        board = self.partial()
        self.assertEqual([row['id'] for row in board['rows']], ['gold'])
        metals.validate(board, self.now)
        self.assertIn('نرخ نقره تأیید نشد', renderer.caption(board))
        self.assertNotIn('51.50', renderer.caption(board))
        self.providers['alanchand']['gold']['price'] = '2100'
        self.providers['dolarchand']['gold']['price'] = '2100'
        with self.assertRaises(metals.GoldError):
            metals.validate(board, self.now)

    def test_gold_only_does_not_hide_a_complete_board_or_invent_ratio(self):
        board = self.partial()
        board['ratio'] = '40'
        with self.assertRaises(metals.GoldError):
            metals.validate(board, self.now)
        board['ratio'] = None
        self.providers['alanchand']['silver']['price'] = '50.01'
        self.providers['dolarchand']['silver']['price'] = '50.01'
        with self.assertRaises(metals.GoldError):
            metals.validate(board, self.now)

    def test_gold_only_cannot_bypass_servix_requirement(self):
        self.providers['servix']['gold']['price'] = '1900'
        with self.assertRaises(metals.GoldError):
            metals.assess(self.providers, self.now, gold_only=True)

    def test_render_partial_with_real_fonts(self):
        asset = Path(__file__).resolve().parents[2] / 'telegram-exchange-bots-instagram'
        if not (asset/'fonts/Vazirmatn-Regular.ttf').is_file():
            self.skipTest('Local preview assets unavailable')
        with tempfile.TemporaryDirectory() as temp, patch.object(renderer,'labels',return_value=('تاریخ نمونه','Sample date',None)):
            paths = renderer.render(self.partial(), temp, asset, preview=True)
            self.assertEqual(len(paths), 1)
            self.assertTrue(Path(paths[0]).is_file())

    def test_observations_require_verified_complete_24h_snapshot(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE gold_history(day TEXT, observed_at TEXT, prices_json TEXT, media_id TEXT)')
        con.execute('CREATE TABLE gold_observations(observed_at TEXT, snapshot_json TEXT)')
        observed = (self.now - timedelta(hours=24)).isoformat()
        rows = [dict(id=key, price='100') for key in gold.SPEC]
        snap = dict(generated_at=observed, status='verified', rows=rows)
        con.execute('INSERT INTO gold_observations VALUES (?,?)', (observed, json.dumps(snap)))
        with patch.object(gold, 'validate', return_value=None):
            self.assertEqual(set(gold.comparison(con, self.now, 24)), set(gold.SPEC))
            self.assertEqual(gold.comparison(con, self.now + timedelta(hours=2), 24), {})
        with patch.object(gold, 'validate', side_effect=gold.GoldError('bad source')):
            self.assertEqual(gold.comparison(con, self.now, 24), {})
        con.close()

    def test_upgrade_preview_rechecks_consensus_without_requiring_one_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            with sqlite3.connect(state/'gold.sqlite3') as con:
                con.execute('CREATE TABLE gold_previews(runtime_hash TEXT, assets_hash TEXT, created_at REAL, snapshot_json TEXT)')
                con.execute('CREATE TABLE gold_history(day TEXT, observed_at TEXT, prices_json TEXT, media_id TEXT)')
                con.execute('INSERT INTO gold_previews VALUES (?,?,?,?)',
                            ('hash', 'hash', time.time(), json.dumps({'status':'verified','rows':[]})))
            con.close()
            with patch.object(gold, 'STATE', state), patch.object(gold, 'fingerprint', return_value='hash'), \
                 patch.object(gold, 'validate') as validate, patch.object(activation.subprocess, 'run'):
                activation.gold_probe(ROOT)
                validate.assert_called_once()
            with patch.object(gold, 'STATE', state), patch.object(gold, 'fingerprint', return_value='hash'), \
                 patch.object(gold, 'validate', side_effect=gold.GoldError('bad quorum')), \
                 patch.object(activation.subprocess, 'run'):
                with self.assertRaises(gold.GoldError):
                    activation.gold_probe(ROOT)


if __name__ == '__main__':
    unittest.main()

