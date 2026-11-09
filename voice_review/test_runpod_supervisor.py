from contextlib import closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import runpod_lease_store as leases
import runpod_supervisor as supervisor
import runpod_watchdog
from test_runpod_watchdog import FakeAPI


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.con = leases.connect(self.root / 'private' / 'leases.sqlite3')
        self.now = time.time()
        created = self.now - 100
        self.started = datetime.fromtimestamp(created, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.lease = leases.reserve(self.con, 'pod-1', .89, now=created)
        leases.start_requested(self.con, self.lease)
        leases.start_confirmed(self.con, self.lease, pod_id='pod-1', provider_status='RUNNING',
                               provider_started_at=self.started)
        self.api = FakeAPI(self.started)
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def run_supervisor(self, config):
        with patch.object(runpod_watchdog, 'pod_lock', return_value=nullcontext(True)):
            return supervisor.run_once(self.con, self.api, state_dir=self.root,
                                       config=config, now=self.now)
    def test_disabled_by_default_even_with_a_lease(self):
        self.assertEqual(self.run_supervisor({'pod_id': 'pod-1'}), 'disabled')
        self.assertEqual(self.api.actions, [])
    def test_unknown_output_prevents_stop_then_retrieved_allows_stop(self):
        config = {'pod_id': 'pod-1', 'enabled': True, 'exclusive_during_managed_job': True}
        self.assertEqual(self.run_supervisor(config), 'manual_review')
        self.assertEqual(self.api.actions, [])
        leases.set_output_pending(self.con, self.lease, pending=False)
        self.assertEqual(self.run_supervisor(config), 'closed')
        self.assertEqual(self.api.actions, [('pod-1', 'stop')])
    def test_other_pod_is_never_adopted(self):
        config = {'pod_id': 'another', 'enabled': True, 'exclusive_during_managed_job': True}
        self.assertEqual(self.run_supervisor(config), 'idle')
        self.assertEqual(self.api.actions, [])
    def test_explicit_exclusive_reservation_is_required(self):
        with self.assertRaises(supervisor.SupervisorError):
            self.run_supervisor({'pod_id': 'pod-1', 'enabled': True})


if __name__ == '__main__': unittest.main()
