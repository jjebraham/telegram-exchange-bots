import os
from pathlib import Path
import tempfile
import unittest

import runpod_worker_lock as worker_lock


@unittest.skipIf(worker_lock.fcntl is None, 'POSIX flock unavailable')
class WorkerLockTests(unittest.TestCase):
    def test_same_pod_blocks_while_other_pods_remain_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            with worker_lock.pod_lock(tmp, 'pod-1') as first:
                self.assertTrue(first)
                with worker_lock.pod_lock(tmp, 'pod-1') as second:
                    self.assertFalse(second)
                with worker_lock.pod_lock(tmp, 'pod-2') as other:
                    self.assertTrue(other)
            with worker_lock.pod_lock(tmp, 'pod-1') as after:
                self.assertTrue(after)

    def test_refuses_non_private_directory_and_bad_pod(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o755)
            with self.assertRaises(worker_lock.WorkerLockError):
                with worker_lock.pod_lock(tmp, 'pod-1'): pass
            os.chmod(tmp, 0o700)
            with self.assertRaises(worker_lock.WorkerLockError):
                with worker_lock.pod_lock(tmp, '../other'): pass


if __name__ == '__main__': unittest.main()
