from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import runpod_supervision_probe as probe
from runpod_systemd_guard import SupervisionError


class SupervisionProbeTests(unittest.TestCase):
    def test_preflight_requires_bounded_service_and_no_network(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)
        self.assertTrue(probe.check(Path.home(), runner=runner))
        self.assertIn('--property=RuntimeMaxSec=420s', calls[0])
        self.assertIn('--wait', calls[0])
        self.assertNotIn('runpod.io', repr(calls))
    def test_failed_preflight_stops_startup(self):
        def runner(args, **kwargs): return subprocess.CompletedProcess(args, 1)
        with self.assertRaises(SupervisionError): probe.check(Path.home(), runner=runner)
    def test_race_while_service_activates_is_retried(self):
        with patch.object(probe, 'validate_current_unit', side_effect=[SupervisionError('not active'), True]):
            self.assertTrue(probe.validate_with_retry('unit', wait=lambda seconds: None))


if __name__ == '__main__': unittest.main()
