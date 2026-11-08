from contextlib import closing
from datetime import datetime, timezone
import tempfile
import threading
import unittest
from pathlib import Path

import runpod_lease_store as leases


class LeaseTests(unittest.TestCase):
    def test_simultaneous_workers_cannot_both_reserve_same_pod(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'private' / 'leases.sqlite3'
            with closing(leases.connect(path)):
                pass
            barrier = threading.Barrier(2)
            outcomes = []
            def worker():
                with closing(leases.connect(path)) as con:
                    barrier.wait(timeout=5)
                    try:
                        leases.reserve(con, 'pod-1', .89)
                        outcomes.append('reserved')
                    except leases.LeaseError:
                        outcomes.append('blocked')
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
            self.assertEqual(sorted(outcomes), ['blocked', 'reserved'])

    def test_one_active_lease_across_connections_and_verified_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'private' / 'leases.sqlite3'
            with closing(leases.connect(path)) as first, closing(leases.connect(path)) as second:
                lease = leases.reserve(first, 'pod-1', .89)
                with self.assertRaises(leases.LeaseError): leases.reserve(second, 'pod-1', .89)
                leases.start_requested(first, lease)
                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                with self.assertRaises(leases.LeaseError): leases.cancel_unused_reservation(first, lease)
                with self.assertRaises(leases.LeaseError):
                    leases.start_confirmed(first, lease, pod_id='wrong', provider_status='RUNNING',
                                           provider_started_at=timestamp)
                with self.assertRaises(leases.LeaseError):
                    leases.start_confirmed(first, lease, pod_id='pod-1', provider_status='STARTING',
                                           provider_started_at=timestamp)
                with self.assertRaises(leases.LeaseError):
                    leases.start_confirmed(first, lease, pod_id='pod-1', provider_status='RUNNING',
                                           provider_started_at='2020-01-01T00:00:00Z')
                leases.start_confirmed(first, lease, pod_id='pod-1', provider_status='RUNNING',
                                       provider_started_at=timestamp)
                leases.stop_requested(first, lease)
                with self.assertRaises(leases.LeaseError):
                    leases.close_confirmed(first, lease, pod_id='pod-1', provider_status='RUNNING')
                leases.close_confirmed(first, lease, pod_id='pod-1', provider_status='EXITED')
                self.assertTrue(leases.reserve(second, 'pod-1', .89))

    def test_uncertain_action_survives_reopen_and_cannot_be_released(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'private' / 'leases.sqlite3'
            with closing(leases.connect(path)) as con:
                lease = leases.reserve(con, 'pod-1', .89)
                leases.start_requested(con, lease)
                leases.action_uncertain(con, lease)
            with closing(leases.connect(path)) as con:
                self.assertEqual(con.execute('SELECT state FROM leases').fetchone()[0], 'ACTION_UNCERTAIN')
                with self.assertRaises(leases.LeaseError):
                    leases.close_confirmed(con, lease, pod_id='pod-1', provider_status='EXITED')
                with self.assertRaises(leases.LeaseError): leases.reserve(con, 'pod-1', .89)

    def test_only_unused_reservations_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as root, closing(leases.connect(Path(root) / 'p' / 'lease.db')) as con:
            lease = leases.reserve(con, 'pod-1', .89)
            leases.cancel_unused_reservation(con, lease)
            self.assertTrue(leases.reserve(con, 'pod-1', .89))

    def test_outputs_are_protected_until_worker_records_safe_state(self):
        with tempfile.TemporaryDirectory() as root, closing(leases.connect(Path(root) / 'p' / 'lease.db')) as con:
            lease = leases.reserve(con, 'pod-1', .89)
            self.assertEqual(con.execute('SELECT output_pending FROM leases').fetchone()[0], 1)
            leases.set_output_pending(con, lease, pending=False)
            self.assertEqual(con.execute('SELECT output_pending FROM leases').fetchone()[0], 0)
            leases.set_output_pending(con, lease, pending=True)
            self.assertEqual(con.execute('SELECT output_pending FROM leases').fetchone()[0], 1)


if __name__ == '__main__': unittest.main()
