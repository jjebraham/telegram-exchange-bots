import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install_runpod_watchdog as installer
import runpod_watchdog_service as service


class InstallerTests(unittest.TestCase):
    def prepare(self, home):
        root = home / '.config/kiani-instagram-runpod'
        root.mkdir(parents=True, mode=0o700)
        config = root / 'config.json'
        config.write_text(json.dumps({'pod_id': 'pod-1', 'enabled': False}))
        config.chmod(0o600)
    def test_installs_disabled_timer_only_after_fresh_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.prepare(home)
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                if args[-2:] == ['start', installer.SERVICE]: service.run_once(home)
                code = 1 if 'is-enabled' in args else 0
                return subprocess.CompletedProcess(args, code)
            units = {installer.SERVICE: 'service', installer.TIMER: 'timer'}
            with patch.object(installer, 'unit_contents', return_value=units):
                result = installer.install(home, home / 'runtime', runner=runner)
            self.assertFalse(result['automation_enabled'])
            self.assertTrue(result['timer_active'])
            self.assertTrue(any('enable' in call for call in calls))
            self.assertFalse(json.loads((home / '.config/kiani-instagram-runpod/config.json').read_text())['enabled'])

    def test_conflicting_unit_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.prepare(home)
            directory = home / '.config/systemd/user'
            directory.mkdir(parents=True)
            path = directory / installer.SERVICE
            path.write_text('existing user service')
            units = {installer.SERVICE: 'new service', installer.TIMER: 'timer'}
            with patch.object(installer, 'unit_contents', return_value=units), \
                    self.assertRaises(installer.InstallError):
                installer.install(home, home / 'runtime')
            self.assertEqual(path.read_text(), 'existing user service')

    def test_partially_failed_enable_rolls_back_new_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.prepare(home)
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                if args[-2:] == ['start', installer.SERVICE]: service.run_once(home)
                code = 1 if 'is-enabled' in args or 'enable' in args else 0
                return subprocess.CompletedProcess(args, code)
            units = {installer.SERVICE: 'service', installer.TIMER: 'timer'}
            with patch.object(installer, 'unit_contents', return_value=units), \
                    self.assertRaises(installer.InstallError):
                installer.install(home, home / 'runtime', runner=runner)
            self.assertTrue(any('disable' in call for call in calls))
            self.assertFalse((home / '.config/systemd/user' / installer.SERVICE).exists())
            self.assertFalse((home / '.config/systemd/user' / installer.TIMER).exists())


if __name__ == '__main__': unittest.main()
