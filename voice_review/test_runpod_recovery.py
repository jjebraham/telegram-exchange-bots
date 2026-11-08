from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

import runpod_lease_store as leases
import runpod_watchdog as watchdog
from test_runpod_watchdog import FakeAPI


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = leases.connect(Path(self.tmp.name) / 'p' / 'leases.db')
        self.now = time.time()
        self.created = self.now - 1900
        self.started = datetime.fromtimestamp(self.created, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.lease = leases.reserve(self.con, 'pod-1', .89, now=self.created)
        leases.set_output_pending(self.con, self.lease, pending=False)
        leases.start_requested(self.con, self.lease)
        self.api = FakeAPI(self.started)
        self.kw = dict(expected_pod_id='pod-1', exclusive=True, worker_lock_held=True,
                       worker_active=False, output_pending=False, job_done=True, now=self.now)
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def tick(self): return watchdog.tick(self.con, self.api, self.lease, **self.kw)
    def test_crash_after_start_request_is_reconciled_and_stopped(self):
        self.assertEqual(self.tick(), 'closed')
        self.assertEqual(self.api.actions, [('pod-1', 'stop')])
    def test_ambiguous_start_is_reconciled_if_matching_pod_is_running(self):
        leases.action_uncertain(self.con, self.lease)
        self.assertEqual(self.tick(), 'closed')
        self.assertEqual(self.api.actions, [('pod-1', 'stop')])
    def test_ambiguous_start_is_not_closed_just_because_pod_is_stopped(self):
        leases.action_uncertain(self.con, self.lease)
        self.api.pod['status'] = 'EXITED'
        self.assertEqual(self.tick(), 'manual_review')
        self.assertEqual(self.con.execute('SELECT state FROM leases').fetchone()[0], 'ACTION_UNCERTAIN')
        self.assertEqual(self.api.actions, [])
    def test_unrelated_later_start_is_not_stopped(self):
        self.api.pod['startedAt'] = datetime.fromtimestamp(self.now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(self.tick(), 'manual_review')
        self.assertEqual(self.api.actions, [])
    def test_ambiguous_stop_closes_if_provider_reports_stopped(self):
        leases.start_confirmed(self.con, self.lease, pod_id='pod-1', provider_status='RUNNING',
                               provider_started_at=self.started)
        leases.stop_requested(self.con, self.lease)
        leases.action_uncertain(self.con, self.lease)
        self.api.pod['status'] = 'EXITED'
        self.assertEqual(self.tick(), 'closed')
        self.assertEqual(self.api.actions, [])


if __name__ == '__main__': unittest.main()
