import json
import unittest
from unittest.mock import patch

import runpod_audit as audit


class AuditTests(unittest.TestCase):
    def test_inventory_paginates_and_rejects_repeated_cursor(self):
        pages = [
            {'pods': [{'id': 'one'}], 'pagination': {'hasNextPage': True, 'nextCursor': 'next'}},
            {'pods': [{'id': 'two'}], 'pagination': {'hasNextPage': False}},
        ]
        seen = []
        def request(path, token, params):
            seen.append((path, dict(params)))
            return pages[len(seen) - 1]
        self.assertEqual(len(audit.list_pods('secret', request=request)), 2)
        self.assertEqual(seen[1][1]['cursor'], 'next')
        def repeated(*args):
            return {'pods': [], 'pagination': {'hasNextPage': True, 'nextCursor': 'again'}}
        with self.assertRaises(audit.AuditError):
            audit.list_pods('secret', request=repeated)

    def test_summary_omits_credentials_and_handles_bad_values(self):
        result = audit.safe_summary({'id': 'abc', 'status': 'RUNNING', 'env': {'KEY': 'secret'},
            'gpu': {'id': 'NVIDIA RTX', 'count': 1}, 'cost': float('nan'),
            'ssh': {'direct': {'host': 'example.test', 'port': 22, 'command': 'secret'}}})
        self.assertNotIn('secret', json.dumps(result))
        self.assertIsNone(result['hourly_compute_usd'])
        self.assertEqual(result['status'], 'RUNNING')

    def test_request_uses_get_and_blocks_other_paths(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{}'
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return Response()
        opener = Opener()
        with patch.object(audit, 'build_opener', return_value=opener):
            audit.get_json('/pods', 'secret')
        self.assertEqual(opener.request.get_method(), 'GET')
        with self.assertRaises(audit.AuditError):
            audit.get_json('/pods/id/action', 'secret')


if __name__ == '__main__':
    unittest.main()
