from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
import json,sqlite3,tempfile,time,unittest
from unittest.mock import patch,Mock
import runpod_ephemeral as gpu
import runpod_lease_store as leases
from runpod_reel_render import RenderError,private_write


class DisposableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.state=gpu.paths(self.home);self.state.mkdir(parents=True,mode=0o700)
        self.root=self.state/('render-'+'a'*32);self.root.mkdir(mode=0o700)
        self.session={'state':'RENDERING','before':['original-pod'],'name':'kiani-reel-'+'a'*32,
                      'pod_id':'new-pod','nonce':'a'*32,'unit':'worker.service','created_at':time.time()-20,'rate':.59}
        self.pod={'id':'new-pod','name':self.session['name'],'status':'RUNNING','cost':.59,'mounts':{},
                  'createdAt':datetime.now(timezone.utc).isoformat(),'locked':False,'actions':['stop']}
        private_write(self.root/'session.json',self.session)
        with closing(leases.connect(self.state/'leases.sqlite3')) as con:
            gpu.spend_guard(con)
            con.execute('INSERT INTO render_spend VALUES(?,?,?,?,?)',(self.root.name,'2026-11','a'*32,.5,'RESERVED'))
    def tearDown(self):self.tmp.cleanup()
    def cleanup(self,**patches):
        from contextlib import ExitStack,nullcontext
        with ExitStack() as stack:
            stack.enter_context(patch('runpod_worker_lock.pod_lock',return_value=nullcontext(True)))
            stack.enter_context(patch.object(gpu,'active',return_value=False))
            for name,value in patches.items():stack.enter_context(patch.object(gpu,name,value))
            return gpu.cleanup(self.home,self.root)
    def test_crashed_reproducible_job_stops_then_deletes_only_its_created_pod(self):
        api=Mock();api.status.return_value=dict(self.pod,status='EXITED')
        http=Mock(return_value=None)
        self.assertEqual(self.cleanup(matching_pod=Mock(return_value=self.pod),api=Mock(return_value=api),http=http),'FAILED_STOPPED')
        api.transition.assert_called_once_with('new-pod','stop')
        self.assertEqual(http.call_args.args[1],'/v2/pods/new-pod')
        self.assertEqual(http.call_args.kwargs['method'],'DELETE')
        self.assertTrue(json.loads((self.root/'session.json').read_text())['shutdown_confirmed'])
    def test_original_or_restarted_pod_is_never_adopted(self):
        for p in (dict(self.pod,id='original-pod'),dict(self.pod,name='someone-else'),dict(self.pod,mounts={'persistent':{'size':50}})):
            self.assertFalse(gpu.owned(p,self.session))
        session=dict(self.session,started_at='2026-11-10T00:00:00Z')
        self.assertFalse(gpu.owned(dict(self.pod,startedAt='2026-11-10T01:00:00Z'),session))
    def test_unknown_creation_remains_reserved_and_is_not_retried(self):
        self.session.update(state='CREATE_REQUESTED');self.session.pop('pod_id')
        private_write(self.root/'session.json',self.session)
        http=Mock()
        self.assertEqual(self.cleanup(matching_pod=Mock(return_value=None),http=http),'creation_unconfirmed')
        http.assert_not_called()
        self.assertEqual(json.loads((self.root/'session.json').read_text())['state'],'CREATE_REQUESTED')
    def test_preparing_worker_crash_cancels_before_any_possible_create(self):
        private_write(self.root/'session.json',dict(self.session,state='PREPARING',created_at=time.time()-60))
        lookup=Mock();self.assertEqual(self.cleanup(matching_pod=lookup),'NO_CAPACITY');lookup.assert_not_called()
    def test_watchdog_cannot_cancel_a_worker_before_systemd_has_started_it(self):
        private_write(self.root/'session.json',dict(self.session,state='PREPARING',created_at=time.time()))
        lookup=Mock();self.assertEqual(self.cleanup(matching_pod=lookup),'queued');lookup.assert_not_called()
    def test_live_bounded_worker_is_watched_without_requesting_stop(self):
        from contextlib import nullcontext
        with patch('runpod_worker_lock.pod_lock',return_value=nullcontext(True)),patch.object(gpu,'active',return_value=True),patch.object(gpu,'matching_pod') as lookup:
            self.assertEqual(gpu.cleanup(self.home,self.root),'watching');lookup.assert_not_called()
        self.assertEqual(json.loads((self.root/'watchdog.json').read_text())['result'],'watching')
    def test_failed_delete_stays_stopped_and_is_retried_by_independent_sweep(self):
        stopped=dict(self.pod,status='EXITED')
        self.assertEqual(self.cleanup(matching_pod=Mock(return_value=stopped),http=Mock(side_effect=OSError())),'stopped_cleanup_pending')
        saved=json.loads((self.root/'session.json').read_text());self.assertTrue(saved['shutdown_confirmed']);self.assertTrue(saved['delete_requested'])
        self.assertEqual(self.cleanup(matching_pod=Mock(return_value=None)),'FAILED_STOPPED')
    def test_watchdog_acknowledgement_waits_for_a_pass_after_worker_start(self):
        calls=[]
        def start(*args):
            calls.append(True)
            if len(calls)==2: private_write(self.root/'watchdog.json',{'time':time.time(),'result':'watching'})
        with patch.object(gpu,'command',side_effect=start): gpu.acknowledge_watchdog(self.root,wait=lambda _:None)
        self.assertEqual(len(calls),2)
    def test_failed_recovery_journal_write_cannot_leave_a_committed_budget_reservation(self):
        fresh=self.state/('render-'+'b'*32);fresh.mkdir(mode=0o700)
        with closing(leases.connect(self.state/'leases.sqlite3')) as con:con.execute('DELETE FROM render_spend')
        with patch.object(gpu,'verify_watchdog'),patch.object(gpu,'private_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):gpu.submit(self.home,fresh)
        with closing(leases.connect(self.state/'leases.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM render_spend').fetchone()[0],0)
    def test_first_transaction_crash_without_spend_table_is_recoverable(self):
        with closing(leases.connect(self.state/'leases.sqlite3')) as con:con.execute('DROP TABLE render_spend')
        private_write(self.root/'session.json',dict(self.session,state='PREPARING',created_at=time.time()-60))
        self.assertEqual(self.cleanup(),'NO_CAPACITY')
    def test_retention_never_discards_active_inputs(self):
        with patch.object(gpu,'cleanup_inputs') as prune:
            self.assertFalse(gpu.prune_session(self.root,now=time.time()+200000));prune.assert_not_called()
            private_write(self.root/'session.json',dict(self.session,state='FAILED_STOPPED',stopped_at=time.time()-200000))
            self.assertTrue(gpu.prune_session(self.root));prune.assert_called_once_with(self.root)


if __name__=='__main__':unittest.main()
