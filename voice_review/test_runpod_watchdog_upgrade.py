from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install_runpod_watchdog as installer
import runpod_watchdog_service as service
import upgrade_runpod_watchdog as upgrade


class UpgradeTests(unittest.TestCase):
    def setup_home(self, home):
        config_dir = home / '.config/kiani-instagram-runpod'
        config_dir.mkdir(parents=True, mode=0o700)
        config = config_dir / 'config.json'
        config.write_text(json.dumps({'pod_id': 'pod-1', 'enabled': False}))
        config.chmod(0o600)
        units = home / '.config/systemd/user'
        units.mkdir(parents=True)
        (units / installer.SERVICE).write_text('old-service')
        (units / installer.TIMER).write_text('timer')
        return units
    @staticmethod
    def units(home, runtime):
        return {installer.SERVICE: 'old-service' if 'a' * 40 in str(runtime) else 'new-service',
                installer.TIMER: 'timer'}
    def test_upgrade_backs_up_and_verifies_disabled_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = self.setup_home(home)
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                if args[-2:] == ['start', installer.SERVICE]: service.run_once(home)
                return subprocess.CompletedProcess(args, 0)
            with patch.object(installer, 'unit_contents', side_effect=self.units), \
                    patch.object(upgrade, 'pod_lock', return_value=nullcontext(True)):
                result = upgrade.upgrade(home, home / 'new', 'a' * 40, runner=runner)
            self.assertEqual((directory / installer.SERVICE).read_text(), 'new-service')
            self.assertEqual((Path(result['backup']) / installer.SERVICE).read_text(), 'old-service')
            self.assertTrue(any(call[-2:] == ['start', installer.TIMER] for call in calls))
    def test_conflict_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = self.setup_home(home)
            (directory / installer.SERVICE).write_text('unrelated')
            with patch.object(installer, 'unit_contents', side_effect=self.units), \
                    patch.object(upgrade, 'pod_lock', return_value=nullcontext(True)), \
                    self.assertRaises(installer.InstallError):
                upgrade.upgrade(home, home / 'new', 'a' * 40)
            self.assertEqual((directory / installer.SERVICE).read_text(), 'unrelated')
    def test_failed_service_restart_restores_original_and_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = self.setup_home(home)
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1 if args[-2:] == ['start', installer.SERVICE] else 0)
            with patch.object(installer, 'unit_contents', side_effect=self.units), \
                    patch.object(upgrade, 'pod_lock', return_value=nullcontext(True)), \
                    self.assertRaises(installer.InstallError):
                upgrade.upgrade(home, home / 'new', 'a' * 40, runner=runner)
            self.assertEqual((directory / installer.SERVICE).read_text(), 'old-service')
            self.assertTrue(any(call[-2:] == ['start', installer.TIMER] for call in calls))


if __name__ == '__main__': unittest.main()
