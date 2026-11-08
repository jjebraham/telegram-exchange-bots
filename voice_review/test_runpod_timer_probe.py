import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runpod_timer_probe as timer


class TimerProbeTests(unittest.TestCase):
    def test_only_stops_the_nonce_unit_created_by_the_probe(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            (home / '.local/state/kiani-instagram-voice-review').mkdir(parents=True)
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[0].endswith('systemd-run'):
                    Path(args[-1]).touch()
                return subprocess.CompletedProcess(args, 0)
            with patch.object(timer.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
                    patch.object(timer.subprocess, 'run', side_effect=run):
                self.assertEqual(timer.probe(home), 'independent timer fired')
            self.assertEqual(len(calls), 2)
            unit = next(x.split('=', 1)[1] for x in calls[0] if x.startswith('--unit='))
            self.assertEqual(calls[1][-2:], [unit + '.timer', unit + '.service'])
            self.assertNotIn('runpod.io', repr(calls))

    def test_unavailable_dependencies_fail_closed(self):
        with tempfile.TemporaryDirectory() as root, patch.object(timer.shutil, 'which', return_value=None), \
                patch.object(timer.subprocess, 'run') as run:
            self.assertEqual(timer.probe(Path(root)), 'unavailable')
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
