"""Offline tests for the bounded source-consistency retry."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent/'weekly-market-comparison'))
import weekly_market_data as data


class PairRetryTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.raw = {'servix_catalog': ('old catalog', 'old cat hash'),
                    'servix_prices': ('old prices', 'old price hash')}

    def test_one_retry_rechecks_the_new_pair(self):
        def fetch(url, key):
            return (('new catalog','new cat hash') if url == data.CATALOG else
                    ('new prices','new price hash'))
        with patch.object(data, 'decode', side_effect=lambda value:value), \
             patch.object(data, 'fetch', side_effect=fetch) as fetch_mock, \
             patch.object(data, 'servix', side_effect=[
                 data.GoldError('Servix weekly value and catalog differ: btc'),
                 {'btc': {'price':'100'}}]) as verify:
            result, moment, retried = data.consistent_servix_pair(self.raw, 'secret', self.now, self.now)
        self.assertTrue(retried)
        self.assertEqual(result['btc']['price'], '100')
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(verify.call_args.args[:4], ('new catalog','new prices','new cat hash','new price hash'))
        self.assertGreaterEqual(moment, self.now)

    def test_other_errors_and_late_window_never_retry(self):
        for message, anchor in [
            ('Servix weekly spread exceeds one percent.', self.now),
            ('Servix weekly value and catalog differ: btc', self.now - timedelta(minutes=3)),
        ]:
            with self.subTest(message=message), patch.object(data,'decode',side_effect=lambda x:x), \
                 patch.object(data,'servix',side_effect=data.GoldError(message)), \
                 patch.object(data,'fetch') as fetch:
                with self.assertRaises(data.GoldError):
                    data.consistent_servix_pair(self.raw, 'secret', self.now, anchor)
                fetch.assert_not_called()

    def test_second_mismatch_is_not_accepted(self):
        err = data.GoldError('Servix weekly midpoint and sides differ: eth')
        with patch.object(data,'decode',side_effect=lambda x:x), \
             patch.object(data,'fetch',return_value=('new','digest')), \
             patch.object(data,'servix',side_effect=err) as verify:
            with self.assertRaises(data.GoldError):
                data.consistent_servix_pair(self.raw, 'secret', self.now, self.now)
            self.assertEqual(verify.call_count, 2)


if __name__ == '__main__':
    unittest.main()

