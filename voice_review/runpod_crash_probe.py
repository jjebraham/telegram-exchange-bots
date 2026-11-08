#!/usr/bin/env python3
"""Simulate a crashed renderer and independent watchdog using a fake Pod only."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import runpod_lease_store as leases
import runpod_watchdog as watchdog
from runpod_worker_lock import pod_lock

POD = 'fake-pod'


def checked_directory(path):
    root = (Path.home() / '.local/state/kiani-instagram-voice-review').resolve()
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root or not path.name.startswith('crash-probe-'):
        raise ValueError('Invalid test directory.')
    return path.resolve()


def fake_worker(directory):
    directory = checked_directory(directory)
    created = time.time() - 1900
    started = datetime.fromtimestamp(created, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with pod_lock(directory, POD) as held:
        if not held:
            raise ValueError('Fake Pod lock is already held.')
        with closing(leases.connect(directory / 'lease.sqlite3')) as con:
            lease = leases.reserve(con, POD, .89, now=created)
            leases.start_requested(con, lease)
            leases.start_confirmed(con, lease, pod_id=POD, provider_status='RUNNING', provider_started_at=started)
        (directory / 'lease-id').write_text(lease, encoding='ascii')
        # Simulate an abrupt exit while holding the OS lock; the OS releases it.
        os._exit(17)


class FakePodAPI:
    def __init__(self, started):
        self.actions = []
        self.started = started
    def status(self, pod_id):
        return {'id': POD, 'status': 'RUNNING', 'startedAt': self.started, 'actions': ['stop'], 'locked': False}
    def transition(self, pod_id, action):
        if pod_id != POD or action != 'stop':
            raise ValueError('Unexpected simulated action.')
        self.actions.append(action)
        return {'id': POD, 'status': 'EXITED'}


def fake_watchdog(directory):
    directory = checked_directory(directory)
    if not (directory / 'worker-exited').is_file():
        raise ValueError('The simulated worker has not exited.')
    lease = (directory / 'lease-id').read_text(encoding='ascii')
    with closing(leases.connect(directory / 'lease.sqlite3')) as con:
        started = con.execute('SELECT provider_started_at FROM leases WHERE lease_id=?', (lease,)).fetchone()[0]
        api = FakePodAPI(started)
        result = watchdog.locked_tick(con, api, lease, state_dir=directory, expected_pod_id=POD,
                                      exclusive=True, output_pending=False, job_done=False)
        state = con.execute('SELECT state FROM leases WHERE lease_id=?', (lease,)).fetchone()['state']
    pending = directory / 'result.pending'
    pending.write_text(json.dumps({'result': result, 'lease_state': state,
                                  'fake_actions': api.actions}), encoding='ascii')
    os.replace(pending, directory / 'result.json')


def probe(home, *, timeout=30):
    systemd_run, systemctl = shutil.which('systemd-run'), shutil.which('systemctl')
    root = home / '.local/state/kiani-instagram-voice-review'
    if not systemd_run or not systemctl or root.is_symlink() or not root.is_dir():
        return 'unavailable'
    info = root.stat()
    if hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        return 'unsafe state directory'
    unit = 'kiani-watchdog-crash-test-' + uuid.uuid4().hex
    script = str(Path(__file__).resolve())
    with tempfile.TemporaryDirectory(prefix='crash-probe-', dir=root) as temporary:
        os.chmod(temporary, 0o700)
        directory = Path(temporary)
        timer = [systemd_run, '--user', '--quiet', '--collect', '--unit=' + unit,
                 '--on-active=8s', sys.executable, script, '--fake-watchdog', temporary]
        try:
            launched = subprocess.run(timer, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, timeout=10)
            if launched.returncode:
                return 'could not schedule test watchdog'
            worker = subprocess.run([sys.executable, script, '--fake-worker', temporary],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
            if worker.returncode != 17:
                return 'simulated worker did not exit as expected'
            (directory / 'worker-exited').write_text('yes', encoding='ascii')
            deadline = time.monotonic() + timeout
            result_path = directory / 'result.json'
            while time.monotonic() < deadline:
                if result_path.is_file() and not result_path.is_symlink():
                    result = json.loads(result_path.read_text(encoding='ascii'))
                    if result == {'result': 'closed', 'lease_state': 'CLOSED', 'fake_actions': ['stop']}:
                        return 'passed: worker exited and independent watchdog stopped the fake Pod'
                    return 'simulated watchdog returned an unexpected result'
                time.sleep(.5)
            return 'simulated watchdog did not finish before timeout'
        except (OSError, ValueError, subprocess.SubprocessError):
            return 'simulated crash test unavailable'
        finally:
            try:
                subprocess.run([systemctl, '--user', 'stop', unit + '.timer', unit + '.service'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=8)
            except (OSError, subprocess.SubprocessError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--fake-worker')
    group.add_argument('--fake-watchdog')
    args = parser.parse_args()
    if args.fake_worker:
        fake_worker(args.fake_worker)
    elif args.fake_watchdog:
        fake_watchdog(args.fake_watchdog)
    else:
        print('Crash-recovery simulation:', probe(Path.home()), flush=True)
        print('Only a fake Pod was used. No Runpod, Instagram, ElevenLabs or Telegram request was made.', flush=True)


if __name__ == '__main__':
    main()
