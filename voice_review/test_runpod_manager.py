from contextlib import closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runpod_api_client import ActionOutcomeUnknown
import runpod_lease_store as leases
import runpod_manager as manager


class FakeAPI:
    def __init__(self):
        self.started = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.pod = {'id': 'pod-1', 'status': 'EXITED', 'locked': False, 'cost': .89,
                    'actions': ['start'], 'gpu': {'id': 'test', 'count': 1}}
        self.actions = []
        self.uncertain = False
        self.bad_ssh = False
    def status(self, pod_id): return dict(self.pod)
    def transition(self, pod_id, action):
        self.actions.append(action)
        if action == 'start':
            if self.uncertain: raise ActionOutcomeUnknown('fake')
            self.pod.update(status='RUNNING', startedAt=self.started, actions=['stop'],
                            ssh={'direct': {'host': 'example.test', 'port': 2222, 'username': 'root'}},
                            env={'SECRET': 'do-not-transfer'})
            if self.bad_ssh:
                self.pod['ssh']['direct']['host'] = 'bad;command'
        elif action == 'stop':
            self.pod.update(status='EXITED', actions=['start'])
        return dict(self.pod)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.con = leases.connect(self.root / 'private' / 'leases.db')
        self.api = FakeAPI()
        self.kw = dict(state_dir=self.root, pod_id='pod-1', enabled=True, exclusive=True,
                       watchdog_ready=True, bootstrap_ready=True, identity_ready=True,
                       runtime_limit_verified=True, budget_remaining=1,
                       work=lambda pod, lease: 'local-result', verify=lambda result: result == 'local-result')
    def tearDown(self):
        self.con.close()
        self.temp.cleanup()
    def run_job(self, **overrides):
        with patch.object(manager, 'pod_lock', return_value=nullcontext(True)):
            return manager.run_job(self.con, self.api, **dict(self.kw, **overrides))
    def test_verified_output_is_returned_only_after_confirmed_stop(self):
        targets = []
        def work(target, lease):
            targets.append(target)
            return 'local-result'
        self.assertEqual(self.run_job(work=work), 'local-result')
        self.assertNotIn('SECRET', repr(targets))
        self.assertNotIn('do-not-transfer', repr(targets))
        self.assertEqual(targets[0]['ssh_port'], 2222)
        self.assertEqual(self.api.actions, ['start', 'stop'])
        self.assertEqual(self.con.execute('SELECT state FROM leases').fetchone()[0], 'CLOSED')
    def test_missing_safeguards_prevent_start(self):
        for changes in ({'enabled': False}, {'watchdog_ready': False}, {'runtime_limit_verified': False},
                        {'identity_ready': False}, {'exclusive': False}, {'budget_remaining': .1}):
            with self.subTest(changes=changes), self.assertRaises(manager.ManagerError):
                self.run_job(**changes)
        self.assertEqual(self.api.actions, [])
    def test_unverified_output_is_not_discarded_or_published(self):
        with self.assertRaises(manager.ManagerError): self.run_job(verify=lambda result: False)
        self.assertEqual(self.api.actions, ['start'])
        row = self.con.execute('SELECT state,output_pending FROM leases').fetchone()
        self.assertEqual(tuple(row), ('START_CONFIRMED', 1))
    def test_ambiguous_start_is_not_retried_or_assumed_owned(self):
        self.api.uncertain = True
        with self.assertRaises(manager.ManagerError): self.run_job()
        self.assertEqual(self.api.actions, ['start'])
        self.assertEqual(self.con.execute('SELECT state FROM leases').fetchone()[0], 'ACTION_UNCERTAIN')
    def test_running_pod_is_never_adopted(self):
        self.api.pod['status'] = 'RUNNING'
        with self.assertRaises(manager.ManagerError): self.run_job()
        self.assertEqual(self.api.actions, [])

    def test_direct_endpoint_can_be_derived_from_one_verified_runtime_port(self):
        pod={'id':'pod-1','ssh':{'direct':None},'runtime':{'ports':[{'private':22,'public':2345,'ip':'203.0.113.7','type':'tcp'}]}}
        self.assertEqual(manager.render_target(pod)['ssh_port'],2345)
        pod['runtime']['ports'].append(dict(pod['runtime']['ports'][0]))
        with self.assertRaises(manager.ManagerError):manager.render_target(pod)

    def test_unusable_ssh_stops_before_remote_work(self):
        self.api.bad_ssh = True
        with self.assertRaises(manager.ManagerError): self.run_job()
        self.assertEqual(self.api.actions, ['start', 'stop'])
        self.assertEqual(self.con.execute('SELECT state FROM leases').fetchone()[0], 'CLOSED')


if __name__ == '__main__': unittest.main()
