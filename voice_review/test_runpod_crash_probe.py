import json
from contextlib import nullcontext
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runpod_crash_probe as probe


class SimulatedCrash(Exception):
    pass


class CrashProbeTests(unittest.TestCase):
    def test_crashed_fake_worker_is_recovered_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.local/state/kiani-instagram-voice-review/crash-probe-example'
            directory.mkdir(parents=True, mode=0o700)
            with patch.object(Path, 'home', return_value=home), \
                    patch.object(probe.os, '_exit', side_effect=SimulatedCrash), \
                    patch.object(probe, 'pod_lock', return_value=nullcontext(True)), \
                    patch.object(probe.watchdog, 'pod_lock', return_value=nullcontext(True)):
                with self.assertRaises(SimulatedCrash):
                    probe.fake_worker(directory)
                (directory / 'worker-exited').write_text('yes')
                probe.fake_watchdog(directory)
            result = json.loads((directory / 'result.json').read_text())
            self.assertEqual(result, {'result': 'closed', 'lease_state': 'CLOSED', 'fake_actions': ['stop']})

    def test_watchdog_does_not_run_before_worker_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.local/state/kiani-instagram-voice-review/crash-probe-example'
            directory.mkdir(parents=True, mode=0o700)
            with patch.object(Path, 'home', return_value=home), self.assertRaises(ValueError):
                probe.fake_watchdog(directory)


if __name__ == '__main__': unittest.main()
