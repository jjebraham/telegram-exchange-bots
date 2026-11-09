#!/usr/bin/env python3
"""Guarded start/stop-only probe. No SSH, rendering, or Instagram requests.

The probe may temporarily incur Runpod compute charges. It requires the
previously installed watchdog timer and leaves it enabled if recovery is
uncertain. A network outage can prevent any automated shutdown guarantee.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

from runpod_api_client import ActionOutcomeUnknown, ActionRejected, RunpodAPI, RunpodAPIError
from runpod_guard import GuardError, may_start
import install_runpod_watchdog as installer
import runpod_lease_store as leases
import runpod_secrets
import runpod_supervisor
import runpod_systemd_guard
import runpod_supervision_probe
import runpod_watchdog
import runpod_watchdog_service as service
from runpod_worker_lock import pod_lock

WATCHDOG_REVISION = '84304a0cf35cf0a5bc2631beb6435816acb8d971'
UNIT_PREFIX = 'kiani-runpod-api-probe-'


class ProbeError(RuntimeError):
    pass


def validate_probe_limits(cfg):
    limits = cfg['limits']
    if (not cfg['exclusive'] or limits.max_hourly_usd > 1.0 or
            limits.max_uptime_seconds > 1800 or limits.startup_timeout_seconds > 300):
        raise ProbeError('Probe settings exceed the approved Pod limits.')


def set_enabled(path, *, expected, enabled):
    """Change only the enabled flag, refusing unexpected concurrent edits."""
    path = Path(path)
    current = service.private_json(path)
    if current != expected or not isinstance(enabled, bool):
        raise ProbeError('Runpod settings changed; automatic overwrite refused.')
    updated = dict(current, enabled=enabled)
    runpod_supervisor.parse_config(updated)
    fd, temporary = tempfile.mkstemp(prefix='.probe-config-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(updated, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        if service.private_json(path) != current or path.is_symlink():
            raise ProbeError('Runpod settings changed; automatic overwrite refused.')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return updated


def _systemctl(args, *, timeout=15):
    try:
        result = subprocess.run(['systemctl', '--user', *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise ProbeError('The user service manager is unavailable.') from None
    if result.returncode:
        raise ProbeError('A required watchdog service check failed.')


def check_watchdog(home):
    runtime = home / '.local/state/kiani-instagram-manual-news/source' / WATCHDOG_REVISION / 'voice_review'
    expected = installer.unit_contents(home, runtime)
    unit_dir = home / '.config/systemd/user'
    for name, contents in expected.items():
        path = unit_dir / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096 or path.read_text() != contents:
            raise ProbeError('The installed watchdog does not match the reviewed revision.')
    _systemctl(['is-enabled', '--quiet', installer.TIMER])
    _systemctl(['is-active', '--quiet', installer.TIMER])


def verify_locked_watchdog(home):
    """Require a fresh independent watchdog pass while this worker holds the lock."""
    check_watchdog(home)
    started = time.time()
    _systemctl(['start', installer.SERVICE], timeout=75)
    beat = service.private_json(home / '.local/state/kiani-instagram-runpod/watchdog-heartbeat.json')
    if (beat.get('enabled') is not True or beat.get('result') != 'lock_busy' or
            not isinstance(beat.get('time'), (int, float)) or beat['time'] < started - 2):
        raise ProbeError('The independent watchdog did not verify the held worker lock.')


def run_worker(home, lease_id, unit, *, api_factory=RunpodAPI, wait=time.sleep,
               monotonic=time.monotonic, work=None):
    """Run in a verified time-limited process; optional work is reproducible."""
    runpod_supervision_probe.validate_with_retry(unit)
    config_dir = home / '.config/kiani-instagram-runpod'
    state = home / '.local/state/kiani-instagram-runpod'
    cfg_raw = service.private_json(config_dir / 'config.json')
    cfg = runpod_supervisor.parse_config(cfg_raw)
    if not cfg['enabled'] or not cfg['exclusive']:
        raise ProbeError('Managed watchdog is not enabled for the reserved Pod.')
    validate_probe_limits(cfg)
    api = api_factory(runpod_secrets.read(config_dir / 'credentials.env'))
    if not re.fullmatch(r'[a-f0-9]{32}', str(lease_id)):
        raise ProbeError('Invalid probe lease.')
    lock_deadline = monotonic() + 20
    while True:
        with pod_lock(state, cfg['pod_id']) as held:
            if held:
                verify_locked_watchdog(home)
                if service.private_json(config_dir / 'config.json') != cfg_raw:
                    raise ProbeError('Runpod settings changed; the Pod was not started.')
                return _worker_locked(state, cfg, api, lease_id, wait=wait, monotonic=monotonic, work=work)
        if monotonic() >= lock_deadline:
            raise ProbeError('The probe could not acquire the managed Pod lock.')
        wait(1)


def _worker_locked(state, cfg, api, lease_id, *, wait, monotonic, work=None):
    pod_id, limits = cfg['pod_id'], cfg['limits']
    with closing(leases.connect(state / 'leases.sqlite3')) as con:
        row = con.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
        if (not row or row['pod_id'] != pod_id or row['state'] != 'START_REQUESTED' or
                row['output_pending'] != 0):
            raise ProbeError('The probe lease is not ready; no Pod action taken.')
        pod = api.status(pod_id)
        may_start(pod, pod_id, limits, exclusive=cfg['exclusive'], watchdog_ready=True,
                  bootstrap_ready=False, identity_ready=False, worker_lock_held=True,
                  budget_remaining=.5, purpose='api_probe')
        try:
            try:
                pod = api.transition(pod_id, 'start')
            except ActionRejected as exc:
                stopped = api.status(pod_id)
                if stopped.get('id') != pod_id:
                    raise ProbeError('Rejected start identity was not confirmed.')
                leases.start_rejected(con, lease_id, pod_id=pod_id,
                                      provider_status=stopped.get('status'), rejection=exc)
                print('Start refused:', exc.category, '| HTTP', exc.http_status, flush=True)
                return 'start_rejected'
            except ActionOutcomeUnknown as exc:
                print('Start request response:',
                      'HTTP ' + str(exc.http_status) if exc.http_status is not None else 'no verified response',
                      flush=True)
                leases.action_uncertain(con, lease_id)
                raise ProbeError('Start response is uncertain; the watchdog remains enabled.') from None
            deadline = monotonic() + limits.startup_timeout_seconds
            while pod.get('status') in ('PROVISIONING', 'STARTING'):
                if monotonic() >= deadline:
                    leases.action_uncertain(con, lease_id)
                    raise ProbeError('Startup timed out; the watchdog remains enabled.')
                wait(5)
                pod = api.status(pod_id)
            if pod.get('id') != pod_id or pod.get('status') != 'RUNNING':
                leases.action_uncertain(con, lease_id)
                raise ProbeError('Pod did not reach a verified running state.')
            leases.start_confirmed(con, lease_id, pod_id=pod_id, provider_status='RUNNING',
                                   provider_started_at=pod.get('startedAt'),
                                   max_start_delay_seconds=limits.max_uptime_seconds)
            # Render inputs must already be saved on Selenium. This callback
            # must be reproducible: a killed worker leaves no irreplaceable
            # remote output, so the independent watchdog may stop the Pod.
            if work is not None:
                work(pod, lease_id)
            result = runpod_watchdog.tick(con, api, lease_id, expected_pod_id=pod_id, exclusive=True,
                worker_lock_held=True, worker_active=False, output_pending=False, job_done=True, limits=limits)
            if result == 'closed':
                return 'closed'
            raise ProbeError('Stop was not confirmed; the watchdog remains enabled: ' + result)
        finally:
            row = con.execute('SELECT state FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
            if row and row['state'] == 'START_REQUESTED':
                leases.action_uncertain(con, lease_id)
            elif row and row['state'] == 'START_CONFIRMED':
                runpod_watchdog.tick(con, api, lease_id, expected_pod_id=pod_id, exclusive=True,
                    worker_lock_held=True, worker_active=False, output_pending=False, job_done=True, limits=limits)


def begin(home, *, api_factory=RunpodAPI, runtime=None, runner=subprocess.run,
          watchdog_check=check_watchdog, service_call=_systemctl,
          supervision_check=runpod_supervision_probe.check):
    """Enable the watchdog for one API-only probe and queue a bounded worker."""
    home = Path(home).resolve()
    state = home / '.local/state/kiani-instagram-runpod'
    config_dir = home / '.config/kiani-instagram-runpod'
    config_path = config_dir / 'config.json'
    config = service.private_json(config_path)
    cfg = runpod_supervisor.parse_config(config)
    if cfg['enabled'] or not cfg['exclusive']:
        raise ProbeError('The probe requires disabled automation and exclusive managed-job ownership.')
    validate_probe_limits(cfg)
    watchdog_check(home)
    supervision_check(home)
    key = runpod_secrets.read(config_dir / 'credentials.env')
    api = api_factory(key)
    unit = UNIT_PREFIX + uuid.uuid4().hex + '.service'
    runtime = Path(runtime).resolve() if runtime is not None else Path(__file__).resolve().parent
    source_root = (home / '.local/state/kiani-instagram-manual-news/source').resolve()
    if runtime.name != 'voice_review' or runtime.parent.parent != source_root or not re.fullmatch(r'[0-9a-f]{40}', runtime.parent.name):
        raise ProbeError('Probe runtime is not a pinned staged revision.')
    with pod_lock(state, cfg['pod_id']) as held:
        if not held:
            raise ProbeError('A managed Pod job is already active.')
        pod = api.status(cfg['pod_id'])
        plan = may_start(pod, cfg['pod_id'], cfg['limits'], exclusive=cfg['exclusive'], watchdog_ready=True,
                         bootstrap_ready=False, identity_ready=False, worker_lock_held=True,
                         budget_remaining=.5, purpose='api_probe')
        with closing(leases.connect(state / 'leases.sqlite3')) as con:
            lease = leases.reserve(con, cfg['pod_id'], plan['hourly_rate'])
            leases.set_output_pending(con, lease, pending=False)
            active = None
            request_enqueued = False
            try:
                active = set_enabled(config_path, expected=config, enabled=True)
                started = time.time()
                service_call(['start', installer.SERVICE], timeout=75)
                beat = service.private_json(state / 'watchdog-heartbeat.json')
                if (beat.get('enabled') is not True or beat.get('result') != 'lock_busy' or
                        not isinstance(beat.get('time'), (int, float)) or beat['time'] < started - 2):
                    raise ProbeError('The independent watchdog did not verify the held worker lock.')
                leases.start_requested(con, lease)
                request_enqueued = True
                cmd = ['systemd-run', '--user', '--quiet', '--collect', '--no-block', '--unit=' + unit,
                       '--property=Type=exec', '--property=RuntimeMaxSec=420s',
                       '--property=TimeoutStopSec=10s', '--setenv=HOME=' + str(home),
                       sys.executable, str(Path(__file__).resolve()), '--worker', lease, '--unit', unit]
                result = runner(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15)
                if result.returncode:
                    raise ProbeError('The supervised worker could not be confirmed; watchdog remains enabled.')
            except Exception:
                if not request_enqueued:
                    try: leases.cancel_unused_reservation(con, lease)
                    except leases.LeaseError: pass
                    if active is not None:
                        try: set_enabled(config_path, expected=active, enabled=False)
                        except (ProbeError, OSError, ValueError): pass
                raise
    return lease


def finalize(home, lease_id, *, api_factory=RunpodAPI):
    """Disable the watchdog only after a closed lease and a stopped Pod."""
    home = Path(home).resolve()
    state = home / '.local/state/kiani-instagram-runpod'
    config_dir = home / '.config/kiani-instagram-runpod'
    config_path = config_dir / 'config.json'
    config = service.private_json(config_path)
    cfg = runpod_supervisor.parse_config(config)
    if not cfg['enabled']:
        return 'already disabled'
    api = api_factory(runpod_secrets.read(config_dir / 'credentials.env'))
    with pod_lock(state, cfg['pod_id']) as held:
        if not held:
            return 'worker still active'
        with closing(leases.connect(state / 'leases.sqlite3')) as con:
            row = con.execute('SELECT pod_id,state FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
            active = con.execute("SELECT COUNT(*) FROM leases WHERE pod_id=? AND state IN "
                "('RESERVED','START_REQUESTED','START_CONFIRMED','ACTION_UNCERTAIN','STOP_REQUESTED')", (cfg['pod_id'],)).fetchone()[0]
            if not row or row['pod_id'] != cfg['pod_id'] or row['state'] not in ('CLOSED', 'CANCELLED', 'START_REJECTED') or active:
                return 'lease unresolved'
            if api.status(cfg['pod_id']).get('status') != 'EXITED':
                return 'Pod not confirmed stopped'
            set_enabled(config_path, expected=config, enabled=False)
            if row['state'] == 'START_REJECTED':
                return 'start rejected; Pod stopped and watchdog returned to disabled mode'
            return 'stopped and watchdog returned to disabled mode'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker')
    parser.add_argument('--unit')
    parser.add_argument('--finalize')
    args = parser.parse_args()
    home = Path.home()
    if args.worker:
        if not args.unit: raise ProbeError('A supervised worker unit is required.')
        print('API-only worker:', run_worker(home, args.worker, args.unit), flush=True)
        return
    if args.finalize:
        print('Probe finalization:', finalize(home, args.finalize), flush=True)
        return
    lease = begin(home)
    print('Managed API-only probe queued. Lease:', lease, flush=True)
    print('Compute charges may apply; the watchdog remains enabled until the Pod is confirmed stopped.', flush=True)
    deadline = time.monotonic() + 540
    next_update = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = finalize(home, lease)
        if result == 'stopped and watchdog returned to disabled mode':
            print('Probe passed:', result, flush=True)
            return
        if result.startswith('start rejected;'):
            raise ProbeError(result)
        if time.monotonic() >= next_update:
            print('Probe status:', result, '| watchdog remains enabled', flush=True)
            next_update = time.monotonic() + 30
        time.sleep(5)
    raise ProbeError('Probe did not finish; check the Runpod console. The watchdog remains enabled. Lease: ' + lease)


if __name__ == '__main__':
    try:
        main()
    except (ProbeError, GuardError, RunpodAPIError, runpod_systemd_guard.SupervisionError,
            leases.LeaseError, runpod_secrets.SecretError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('Runpod probe stopped:', str(exc) if isinstance(exc, ProbeError) else type(exc).__name__, file=sys.stderr, flush=True)
        print('If a probe was queued, check the Runpod console; the watchdog stays enabled until confirmed stopped.', file=sys.stderr, flush=True)
        raise SystemExit(1)
