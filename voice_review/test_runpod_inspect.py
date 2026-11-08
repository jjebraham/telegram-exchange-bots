import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runpod_inspect as inspect


class InspectionTests(unittest.TestCase):
    def test_detail_omits_secret_values_and_checks_storage(self):
        pod = {'id': 'test-pod', 'status': 'EXITED', 'cost': .89,
               'gpu': {'id': 'NVIDIA GeForce RTX 4090', 'count': 1},
               'mounts': {'persistent': {'size': 20, 'path': '/workspace'}},
               'ports': ['22/tcp'], 'env': {'SSH_PUBLIC_KEY': 'secret-key', 'API_KEY': 'secret-token'},
               'args': 'secret-argument', 'image': 'runpod/pytorch:example'}
        value = inspect.summarize_detail(pod)
        self.assertTrue(value['persistent_at_workspace'])
        self.assertEqual(value['persistent_volume_gb'], 20)
        self.assertTrue(value['ssh_port_22_exposed'])
        self.assertTrue(value['pod_ssh_public_key_configured'])
        self.assertNotIn('secret', json.dumps(value))

    def test_missing_storage_is_unknown_not_false(self):
        value = inspect.summarize_detail({'id': 'test', 'status': 'EXITED'})
        self.assertFalse(value['mount_details_present'])
        self.assertIsNone(value['persistent_volume_gb'])
        self.assertIsNone(value['persistent_at_workspace'])
        self.assertIsNone(value['ssh_port_22_exposed'])

    def test_no_key_makes_no_api_request(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), \
                patch.object(inspect.sys, 'argv', ['runpod_inspect.py', '--pod', 'test']), \
                patch.dict(inspect.os.environ, {'RUNPOD_API_KEY': ''}), \
                patch.object(inspect.getpass, 'getpass', return_value=''), \
                patch.object(inspect, 'get_json', side_effect=AssertionError('unexpected request')), \
                contextlib.redirect_stdout(io.StringIO()):
            inspect.main()


if __name__ == '__main__':
    unittest.main()
