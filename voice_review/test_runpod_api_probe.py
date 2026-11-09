from contextlib import closing, nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runpod_api_client import ActionOutcomeUnknown, ActionRejected
import runpod_api_probe as probe
import runpod_lease_store as leases
import runpod_secrets
import runpod_supervisor
import runpod_watchdog
import runpod_watchdog_service as service


class FakeAPI:
    def __init__(self):
        self.pod = {'id': 'pod-1', 'status': 'EXITED', 'cost': .89, 'locked': False,
                    'gpu': {'id': 'test', 'count': 1}, 'actions': ['start']}
        self.actions = []
        self.uncertain = False
    def status(self, pod_id): return dict(self.pod)
    def transition(self, pod_id, action):
        self.actions.append(action)
        if action == 'start':
            self.pod.update(status='RUNNING', actions=['stop'],
                            startedAt=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            if self.uncertain: raise ActionOutcomeUnknown('fake')
        elif action == 'stop':
            self.pod.update(status='EXITED', actions=['start'])
        return dict(self.pod)


class APIProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.state = self.home / '.local/state/kiani-instagram-runpod'
        self.state.mkdir(parents=True, mode=0o700)
        self.config_dir = self.home / '.config/kiani-instagram-runpod'
        self.config_dir.mkdir(parents=True, mode=0o700)
        self.path = self.config_dir / 'config.json'
        self.data = {'pod_id': 'pod-1', 'enabled': False, 'exclusive_during_managed_job': True}
        self.path.write_text(json.dumps(self.data))
        self.path.chmod(0o600)
        runpod_secrets.write(self.config_dir / 'credentials.env', 'sample-key-123')
        self.runtime = self.home / '.local/state/kiani-instagram-manual-news/source' / ('a' * 40) / 'voice_review'
        self.runtime.mkdir(parents=True)
        self.api = FakeAPI()
    def tearDown(self): self.tmp.cleanup()
    def test_only_flag_is_changed_and_concurrent_edits_are_refused(self):
        active = probe.set_enabled(self.path, expected=self.data, enabled=True)
        self.assertEqual(active, dict(self.data, enabled=True))
        with self.assertRaises(probe.ProbeError):
            probe.set_enabled(self.path, expected=self.data, enabled=False)
        self.assertTrue(service.private_json(self.path)['enabled'])
    def begin(self, *, fail_heartbeat=False, launch_result=0):
        calls = []
        def service_call(args, **kwargs):
            if fail_heartbeat: raise probe.ProbeError('fake heartbeat failure')
            service.heartbeat(self.state, result='lock_busy', enabled=True)
        def runner(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, launch_result)
        with patch.object(probe, 'pod_lock', return_value=nullcontext(True)):
            result = probe.begin(self.home, api_factory=lambda key:self.api, runtime=self.runtime,
                                 runner=runner, watchdog_check=lambda home:None,
                                 service_call=service_call, supervision_check=lambda home:True)
        return result, calls
    def test_preflight_queues_only_bounded_worker_and_keeps_watchdog_on(self):
        lease, calls = self.begin()
        self.assertIn('--property=RuntimeMaxSec=420s', calls[0])
        self.assertEqual(self.api.actions, [])
        self.assertTrue(service.private_json(self.path)['enabled'])
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            row = con.execute('SELECT state,output_pending FROM leases WHERE lease_id=?', (lease,)).fetchone()
            self.assertEqual(tuple(row), ('START_REQUESTED', 0))
    def test_probe_refuses_configured_caps_above_approved_limits(self):
        cfg = runpod_supervisor.parse_config(dict(self.data, max_hourly_usd=1.01))
        with self.assertRaises(probe.ProbeError): probe.validate_probe_limits(cfg)
        cfg = runpod_supervisor.parse_config(dict(self.data, max_uptime_seconds=1801))
        with self.assertRaises(probe.ProbeError): probe.validate_probe_limits(cfg)
    def test_failure_before_queuing_rolls_back_without_start(self):
        with self.assertRaises(probe.ProbeError): self.begin(fail_heartbeat=True)
        self.assertFalse(service.private_json(self.path)['enabled'])
        self.assertEqual(self.api.actions, [])
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT state FROM leases').fetchone()[0], 'CANCELLED')
    def test_uncertain_launch_retains_watchdog_and_lease(self):
        with self.assertRaises(probe.ProbeError): self.begin(launch_result=1)
        self.assertTrue(service.private_json(self.path)['enabled'])
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT state FROM leases').fetchone()[0], 'START_REQUESTED')
    def test_fake_worker_starts_and_stops_without_remote_assets(self):
        cfg = runpod_supervisor.parse_config(dict(self.data, enabled=True))
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            lease = leases.reserve(con, 'pod-1', .89)
            leases.set_output_pending(con, lease, pending=False)
            leases.start_requested(con, lease)
            result = probe._worker_locked(self.state, cfg, self.api, lease, wait=lambda n:None, monotonic=lambda:0)
            self.assertEqual(result, 'closed')
            self.assertEqual(self.api.actions, ['start', 'stop'])
            self.assertEqual(con.execute('SELECT state FROM leases').fetchone()[0], 'CLOSED')
    def test_uncertain_start_is_reconciled_by_watchdog_without_retry(self):
        cfg = runpod_supervisor.parse_config(dict(self.data, enabled=True))
        self.api.uncertain = True
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            lease = leases.reserve(con, 'pod-1', .89)
            leases.set_output_pending(con, lease, pending=False)
            leases.start_requested(con, lease)
            with self.assertRaises(probe.ProbeError):
                probe._worker_locked(self.state, cfg, self.api, lease, wait=lambda n:None, monotonic=lambda:0)
            result = runpod_watchdog.tick(con, self.api, lease, expected_pod_id='pod-1', exclusive=True,
                worker_lock_held=True, worker_active=False, output_pending=False, job_done=True)
            self.assertEqual(result, 'closed')
            self.assertEqual(self.api.actions, ['start', 'stop'])
    def test_worker_requires_fresh_live_watchdog_heartbeat(self):
        def good(*args, **kwargs):
            service.heartbeat(self.state, result='lock_busy', enabled=True)
        def disabled(*args, **kwargs):
            service.heartbeat(self.state, result='disabled', enabled=False)
        with patch.object(probe, 'check_watchdog'), patch.object(probe, '_systemctl', side_effect=good):
            probe.verify_locked_watchdog(self.home)
        with patch.object(probe, 'check_watchdog'), patch.object(probe, '_systemctl', side_effect=disabled):
            with self.assertRaises(probe.ProbeError): probe.verify_locked_watchdog(self.home)

    def test_rejected_capacity_closes_without_blind_retry(self):
        lease, _ = self.begin()
        cfg = runpod_supervisor.parse_config(service.private_json(self.path))
        def rejected(*args):
            raise ActionRejected(http_status=400, category='capacity_unavailable')
        self.api.transition = rejected
        self.assertEqual(probe._worker_locked(self.state, cfg, self.api, lease,
                         wait=lambda n:None, monotonic=lambda:0), 'start_rejected')
        with closing(leases.connect(self.state / 'leases.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT state FROM leases').fetchone()[0], 'START_REJECTED')
        with patch.object(probe, 'pod_lock', return_value=nullcontext(True)):
            self.assertTrue(probe.finalize(self.home, lease, api_factory=lambda key:self.api).startswith('start rejected;'))
        self.assertFalse(service.private_json(self.path)['enabled'])
    def test_finalize_never_disables_watchdog_for_unresolved_lease(self):
        lease, _ = self.begin()
        with patch.object(probe, 'pod_lock', return_value=nullcontext(True)):
            result = probe.finalize(self.home, lease, api_factory=lambda key:self.api)
        self.assertEqual(result, 'lease unresolved')
        self.assertTrue(service.private_json(self.path)['enabled'])
    def test_finalize_disables_watchdog_only_when_stopped_and_closed(self):
        lease, _ = self.begin()
        cfg = runpod_supervisor.parse_config(service.private_json(self.path))
        with closing(leases.connect(self.state / 'leases.sqlite3')):
            probe._worker_locked(self.state, cfg, self.api, lease, wait=lambda n:None, monotonic=lambda:0)
        with patch.object(probe, 'pod_lock', return_value=nullcontext(True)):
            result = probe.finalize(self.home, lease, api_factory=lambda key:self.api)
        self.assertEqual(result, 'stopped and watchdog returned to disabled mode')
        self.assertFalse(service.private_json(self.path)['enabled'])


if __name__ == '__main__': unittest.main()
