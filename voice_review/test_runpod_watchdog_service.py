import json
from pathlib import Path
import tempfile
import unittest

import runpod_secrets
import runpod_watchdog_service as service


class ServiceTests(unittest.TestCase):
    def test_disabled_service_records_heartbeat_without_credentials_or_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.config/kiani-instagram-runpod'
            root.mkdir(parents=True, mode=0o700)
            (root / 'config.json').write_text(json.dumps({'pod_id': 'pod-1', 'enabled': False}))
            (root / 'config.json').chmod(0o600)
            def forbidden(key): raise AssertionError('API must not be constructed')
            self.assertEqual(service.run_once(home, api_factory=forbidden), 'disabled')
            heartbeat = home / '.local/state/kiani-instagram-runpod/watchdog-heartbeat.json'
            self.assertEqual(json.loads(heartbeat.read_text())['result'], 'disabled')
            self.assertFalse((heartbeat.parent / 'leases.sqlite3').exists())

    def test_enabled_idle_service_does_not_contact_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.config/kiani-instagram-runpod'
            root.mkdir(parents=True, mode=0o700)
            path = root / 'config.json'
            path.write_text(json.dumps({'pod_id': 'pod-1', 'enabled': True,
                                        'exclusive_during_managed_job': True}))
            path.chmod(0o600)
            runpod_secrets.write(root / 'credentials.env', 'sample-key-123')
            class InertAPI:
                def __init__(self, key): pass
                def status(self, pod): raise AssertionError('No active lease')
            self.assertEqual(service.run_once(home, api_factory=InertAPI), 'idle')


if __name__ == '__main__': unittest.main()
