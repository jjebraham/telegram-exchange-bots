import unittest

import reel_voice_discovery as discovery


class DiscoveryTests(unittest.TestCase):
    def test_account_pagination(self):
        def get(path, params, key):
            if params.get('next_page_token'):
                return {'voices': [{'name': 'Aylin', 'voice_id': 'zagI4JNTfBvHyoNxaZWj'}], 'has_more': False}
            return {'voices': [], 'has_more': True, 'next_page_token': 'second'}
        self.assertEqual(len(discovery.account_voices('key', get=get)), 1)

    def test_incomplete_inventory_is_not_accepted(self):
        def get(path, params, key):
            return {'voices': [], 'has_more': True, 'next_page_token': 'same'}
        with self.assertRaises(discovery.DiscoveryError):
            discovery.account_voices('key', get=get)

    def test_exact_account_ids_and_shared_matches_stay_distinct(self):
        def get(path, params, key):
            if path == '/v2/voices':
                return {'voices': [{'name': 'Sahar', 'voice_id': 'lIfJn0EyB8lHm00xiGY8'},
                                   {'name': 'Mahdi', 'voice_id': 'a' * 20}], 'has_more': False}
            if params['search'] == 'Mitra':
                return {'voices': [{'name': 'Mitra', 'voice_id': 'b' * 20},
                                   {'name': 'Mitrabelle', 'voice_id': 'c' * 20}], 'has_more': False}
            return {'voices': [], 'has_more': False}
        result = {row['name']: row for row in discovery.inspect('key', get=get)}
        self.assertEqual(result['Sahar']['account_matches'][0]['voice_id'], 'lIfJn0EyB8lHm00xiGY8')
        self.assertEqual(result['Mahdi']['account_matches'][0]['voice_id'], 'a' * 20)
        self.assertEqual(result['Mitra']['account_matches'], [])
        self.assertEqual(result['Mitra']['shared_matches'], [{'name': 'Mitra', 'voice_id': 'b' * 20}])

    def test_shared_lookup_failure_does_not_invent_a_voice(self):
        def get(path, params, key):
            if path == '/v2/voices':
                return {'voices': [], 'has_more': False}
            raise discovery.DiscoveryError('HTTP 403')
        result = discovery.inspect('key', get=get)
        self.assertTrue(all(not row['account_matches'] and not row['shared_matches'] for row in result))
        self.assertTrue(all(row['shared_error'] == 'HTTP 403' for row in result))


if __name__ == '__main__':
    unittest.main()

