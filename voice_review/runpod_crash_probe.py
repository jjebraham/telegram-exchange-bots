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
import traceback
import uuid

POD = 'fake-pod'


def checked_directory(path):
    root = (Path.home() / '.local/state/kiani-instagram-voice-review').resolve()
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root or not path.name.startswith('crash-probe-'):
        raise ValueError('Invalid test directory.')
    return path.resolve()


def fake_worker(directory):
    import runpod_lease_store as leases
    from runpod_worker_lock import pod_lock
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
    import runpod_lease_store as leases
    import runpod_watchdog as watchdog
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


def report_child_error(directory, phase, exc):
    """Write only an exception type and code location, never exception text."""
    try:
        directory = checked_directory(directory)
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        report = {'phase': phase, 'error_type': type(exc).__name__,
                  'location': (Path(last.filename).name + ':' + last.name + ':' + str(last.lineno)) if last else 'unknown'}
        pending = directory / 'error.pending'
        pending.write_text(json.dumps(report), encoding='ascii')
        os.replace(pending, directory / 'error.json')
    except (OSError, ValueError, TypeError):
        pass


def service_diagnostic(systemctl, unit):
    """Return only fixed, non-sensitive systemd state fields."""
    try:
        result = subprocess.run([systemctl, '--user', 'show', unit + '.service',
                                 '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState',
                                 '-p', 'Result', '-p', 'ExecMainCode', '-p', 'ExecMainStatus'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
        allowed = {'LoadState', 'ActiveState', 'SubState', 'Result', 'ExecMainCode', 'ExecMainStatus'}
        fields = []
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if separator and key in allowed and value and all(c.isalnum() or c in '_-' for c in value):
                fields.append(key + '=' + value)
        return ', '.join(fields) if fields else 'service details unavailable'
    except (OSError, subprocess.SubprocessError):
        return 'service details unavailable'


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
                 '--setenv=HOME=' + str(home.resolve()),
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
                error_path = directory / 'error.json'
                if error_path.is_file() and not error_path.is_symlink():
                    return 'child failed: ' + json.dumps(json.loads(error_path.read_text(encoding='ascii')), ensure_ascii=True)
                return 'simulated worker did not exit as expected'
            (directory / 'worker-exited').write_text('yes', encoding='ascii')
            deadline = time.monotonic() + timeout
            result_path = directory / 'result.json'
            while time.monotonic() < deadline:
                error_path = directory / 'error.json'
                if error_path.is_file() and not error_path.is_symlink():
                    error = json.loads(error_path.read_text(encoding='ascii'))
                    return 'child failed: ' + json.dumps(error, ensure_ascii=True)
                if result_path.is_file() and not result_path.is_symlink():
                    result = json.loads(result_path.read_text(encoding='ascii'))
                    if result == {'result': 'closed', 'lease_state': 'CLOSED', 'fake_actions': ['stop']}:
                        return 'passed: worker exited and independent watchdog stopped the fake Pod'
                    return 'simulated watchdog returned an unexpected result'
                time.sleep(.5)
            return 'simulated watchdog did not finish before timeout | ' + service_diagnostic(systemctl, unit)
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
        try:
            fake_worker(args.fake_worker)
        except Exception as exc:
            report_child_error(args.fake_worker, 'worker', exc)
            raise SystemExit(1)
    elif args.fake_watchdog:
        try:
            fake_watchdog(args.fake_watchdog)
        except Exception as exc:
            report_child_error(args.fake_watchdog, 'watchdog', exc)
            raise SystemExit(1)
    else:
        print('Crash-recovery simulation:', probe(Path.home()), flush=True)
        print('Only a fake Pod was used. No Runpod, Instagram, ElevenLabs or Telegram request was made.', flush=True)


if __name__ == '__main__':
    main()
