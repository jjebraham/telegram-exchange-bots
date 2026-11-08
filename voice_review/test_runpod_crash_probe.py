import json
from contextlib import nullcontext
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runpod_crash_probe as probe
import runpod_watchdog as watchdog
import runpod_worker_lock as worker_lock


class SimulatedCrash(Exception):
    pass


class CrashProbeTests(unittest.TestCase):
    @unittest.skipIf(worker_lock.fcntl is None, 'POSIX flock unavailable')
    def test_real_child_exit_then_watchdog_in_separate_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.local/state/kiani-instagram-voice-review'
            root.mkdir(parents=True, mode=0o700)
            directory = root / 'crash-probe-isolated'
            directory.mkdir(mode=0o700)
            environment = dict(os.environ, HOME=str(home))
            worker = subprocess.run([sys.executable, probe.__file__, '--fake-worker', str(directory)],
                                    env=environment, capture_output=True, timeout=15)
            self.assertEqual(worker.returncode, 17)
            (directory / 'worker-exited').write_text('yes')
            check = subprocess.run([sys.executable, probe.__file__, '--fake-watchdog', str(directory)],
                                   env=environment, capture_output=True, timeout=15)
            if check.returncode:
                report = directory / 'error.json'
                self.fail('Watchdog child failed: ' + (report.read_text() if report.exists() else 'no report'))
            result = json.loads((directory / 'result.json').read_text())
            self.assertEqual(result['lease_state'], 'CLOSED')
            self.assertEqual(result['fake_actions'], ['stop'])

    def test_crashed_fake_worker_is_recovered_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.local/state/kiani-instagram-voice-review/crash-probe-example'
            directory.mkdir(parents=True, mode=0o700)
            with patch.object(Path, 'home', return_value=home), \
                    patch.object(probe.os, '_exit', side_effect=SimulatedCrash), \
                    patch.object(worker_lock, 'pod_lock', return_value=nullcontext(True)), \
                    patch.object(watchdog, 'pod_lock', return_value=nullcontext(True)):
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

    def test_child_error_report_never_includes_exception_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            directory = home / '.local/state/kiani-instagram-voice-review/crash-probe-example'
            directory.mkdir(parents=True, mode=0o700)
            try:
                raise ValueError('do-not-print-secret')
            except ValueError as exc:
                with patch.object(Path, 'home', return_value=home):
                    probe.report_child_error(directory, 'watchdog', exc)
            content = (directory / 'error.json').read_text()
            self.assertNotIn('do-not-print-secret', content)
            self.assertEqual(json.loads(content)['error_type'], 'ValueError')


if __name__ == '__main__': unittest.main()
