import unittest

from runpod_guard import GuardError, Limits, estimated_compute_cost, may_start, watchdog_decision


class RunpodGuardTests(unittest.TestCase):
    def setUp(self):
        self.pod = {'id': 'pod1', 'status': 'EXITED', 'locked': False, 'cost': .89,
                    'actions': ['start'], 'gpu': {'id': 'RTX', 'count': 1}}
        self.flags = {'exclusive': True, 'watchdog_ready': True, 'bootstrap_ready': True,
                      'identity_ready': True, 'worker_lock_held': True, 'budget_remaining': 1}
        self.limits = Limits()

    def test_stopped_owned_pod_with_verified_safety_reserves_budget(self):
        result = may_start(self.pod, 'pod1', self.limits, **self.flags)
        self.assertAlmostEqual(result['reserved_compute_usd'], .445)
        self.assertAlmostEqual(estimated_compute_cost(.89, 3600), .89)

    def test_all_guard_flags_are_required(self):
        for key in ('exclusive', 'watchdog_ready', 'bootstrap_ready', 'identity_ready', 'worker_lock_held'):
            with self.subTest(key=key), self.assertRaises(GuardError):
                may_start(self.pod, 'pod1', self.limits, **dict(self.flags, **{key: False}))

    def test_existing_running_or_unknown_pod_is_never_adopted(self):
        for status in ('RUNNING', 'STARTING', 'ERROR', None):
            with self.subTest(status=status), self.assertRaises(GuardError):
                may_start(dict(self.pod, status=status), 'pod1', self.limits, **self.flags)

    def test_expensive_unavailable_wrong_and_budget_are_rejected(self):
        for changes in ({'id': 'other'}, {'cost': 1.01}, {'cost': float('nan')},
                        {'cost': None}, {'gpu': None}, {'actions': []}, {'locked': True}):
            with self.subTest(changes=changes), self.assertRaises(GuardError):
                may_start(dict(self.pod, **changes), 'pod1', self.limits, **self.flags)
        with self.assertRaises(GuardError):
            may_start(self.pod, 'pod1', self.limits, **dict(self.flags, budget_remaining=.44))

    def test_watchdog_never_stops_unknown_or_other_workers(self):
        base = dict(owned=True, ownership_certain=True, worker_active=False,
                    job_done=True, output_pending=False, lease_expired=False)
        self.assertEqual(watchdog_decision(**base), 'stop_owned_pod')
        self.assertEqual(watchdog_decision(**dict(base, owned=False)), 'manual_review')
        self.assertEqual(watchdog_decision(**dict(base, ownership_certain=False)), 'manual_review')
        self.assertEqual(watchdog_decision(**dict(base, worker_active=True)), 'wait')
        self.assertEqual(watchdog_decision(**dict(base, output_pending=True)), 'manual_review')
        self.assertEqual(watchdog_decision(**dict(base, job_done=False)), 'wait')
        self.assertEqual(watchdog_decision(**dict(base, job_done=False, lease_expired=True)), 'stop_owned_pod')

    def test_invalid_limits_and_watchdog_inputs_are_rejected(self):
        with self.assertRaises(GuardError):
            Limits(max_hourly_usd=float('inf'))
        with self.assertRaises(GuardError):
            Limits(max_uptime_seconds=60)
        with self.assertRaises(GuardError):
            watchdog_decision(owned=True, ownership_certain=True, worker_active=None,
                              job_done=True, output_pending=False, lease_expired=False)


if __name__ == '__main__':
    unittest.main()
