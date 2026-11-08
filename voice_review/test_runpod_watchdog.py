from contextlib import closing
from datetime import datetime, timezone
import tempfile
import time
import unittest
from pathlib import Path

from runpod_api_client import ActionOutcomeUnknown
import runpod_lease_store as leases
import runpod_watchdog as watchdog


class FakeAPI:
    def __init__(self, started):
        self.pod = {'id': 'pod-1', 'status': 'RUNNING', 'startedAt': started,
                    'locked': False, 'actions': ['stop']}
        self.actions = []
        self.fail = False
    def status(self, pod_id): return dict(self.pod)
    def transition(self, pod_id, action):
        self.actions.append((pod_id, action))
        if self.fail: raise ActionOutcomeUnknown('test')
        self.pod['status'] = 'EXITED'
        return dict(self.pod)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.con = leases.connect(Path(self.temp.name) / 'state' / 'leases.db')
        self.now = time.time()
        created = self.now - 1900
        started = datetime.fromtimestamp(created, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.lease = leases.reserve(self.con, 'pod-1', .89, now=created)
        leases.start_requested(self.con, self.lease)
        leases.start_confirmed(self.con, self.lease, pod_id='pod-1', provider_status='RUNNING',
                               provider_started_at=started)
        self.api = FakeAPI(started)
        self.options = dict(expected_pod_id='pod-1', exclusive=True, worker_active=False,
                            output_pending=False, job_done=False, now=self.now)
    def tearDown(self):
        self.con.close()
        self.temp.cleanup()
    def test_expired_owned_session_stops_once_and_records_exit(self):
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease, **self.options), 'closed')
        self.assertEqual(self.api.actions, [('pod-1', 'stop')])
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease, **self.options), 'closed')
        self.assertEqual(len(self.api.actions), 1)
    def test_active_worker_and_unretrieved_output_never_stop(self):
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease,
                                       **dict(self.options, worker_active=True)), 'wait')
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease,
                                       **dict(self.options, output_pending=True)), 'manual_review')
        self.assertEqual(self.api.actions, [])
    def test_unowned_or_manually_restarted_pod_never_stops(self):
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease,
                                       **dict(self.options, exclusive=False)), 'manual_review')
        self.api.pod['startedAt'] = '2020-01-01T00:00:00Z'
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease, **self.options), 'manual_review')
        self.assertEqual(self.api.actions, [])
    def test_uncertain_stop_is_never_blindly_retried(self):
        self.api.fail = True
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease, **self.options), 'action_uncertain')
        self.assertEqual(watchdog.tick(self.con, self.api, self.lease, **self.options), 'manual_review')
        self.assertEqual(len(self.api.actions), 1)


if __name__ == '__main__': unittest.main()
