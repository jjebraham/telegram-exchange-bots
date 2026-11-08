#!/usr/bin/env python3
"""Test an independent one-shot user timer without starting or stopping a Pod."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid


def probe(home, *, timeout=25):
    systemd_run = shutil.which('systemd-run')
    systemctl = shutil.which('systemctl')
    touch = shutil.which('touch')
    if not all((systemd_run, systemctl, touch)):
        return 'unavailable'
    state = home / '.local/state/kiani-instagram-voice-review'
    if state.is_symlink() or not state.is_dir():
        return 'unsafe state directory'
    info = state.stat()
    if hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        return 'unsafe state directory'
    unit = 'kiani-watchdog-probe-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='timer-probe-', dir=state) as directory:
        os.chmod(directory, 0o700)
        marker = Path(directory) / 'fired'
        command = [systemd_run, '--user', '--quiet', '--collect', '--unit=' + unit,
                   '--on-active=8s', touch, '--', str(marker)]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
            if result.returncode:
                return 'could not schedule transient timer'
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if marker.is_file() and not marker.is_symlink():
                    return 'independent timer fired'
                time.sleep(.5)
            return 'timer did not fire before timeout'
        except (OSError, subprocess.SubprocessError):
            return 'timer test unavailable'
        finally:
            # These names contain an unpredictable nonce and belong solely to this test.
            try:
                subprocess.run([systemctl, '--user', 'stop', unit + '.timer', unit + '.service'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=8)
            except (OSError, subprocess.SubprocessError):
                pass


if __name__ == '__main__':
    print('Independent timer test:', probe(Path.home()), flush=True)
    print('No Runpod, Instagram, ElevenLabs or Telegram request was made.', flush=True)
