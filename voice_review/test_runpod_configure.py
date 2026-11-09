import json
from pathlib import Path
import tempfile
import unittest

import configure_runpod
from runpod_api_client import RunpodAPIError


class FakeAPI:
    def __init__(self, key): self.key = key
    def status(self, pod_id): return {'id': pod_id, 'status': 'EXITED'}


class ConfigurationTests(unittest.TestCase):
    def test_configures_private_key_but_leaves_automation_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'config'
            result = configure_runpod.configure(root, 'pod-1', 'sample-key-123', api_factory=FakeAPI)
            self.assertFalse(result['enabled'])
            self.assertEqual(result['status'], 'EXITED')
            config = json.loads((root / 'config.json').read_text())
            self.assertFalse(config['enabled'])
            self.assertTrue(config['exclusive_during_managed_job'])
            self.assertNotIn('sample-key-123', json.dumps(config))
            self.assertTrue(configure_runpod.configure(root, 'pod-1', 'sample-key-123', api_factory=FakeAPI)['config_preserved'])

    def test_failed_authentication_never_saves_key(self):
        class InvalidAPI:
            def __init__(self, key): pass
            def status(self, pod_id): raise RunpodAPIError('failed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'config'
            with self.assertRaises(RunpodAPIError):
                configure_runpod.configure(root, 'pod-1', 'sample-key-123', api_factory=InvalidAPI)
            self.assertFalse((root / 'credentials.env').exists())


if __name__ == '__main__': unittest.main()
