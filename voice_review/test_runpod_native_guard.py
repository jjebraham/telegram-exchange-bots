from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch,Mock
import runpod_native_guard as guard


class NativeGuardTests(unittest.TestCase):
    def test_only_pid_one_identity_can_use_native_credential(self):
        fixture=b'RUNPOD_POD_ID=own-pod\x00RUNPOD_API_KEY=runtime-only-secret\x00'
        with patch.object(Path,'read_bytes',return_value=fixture):
            self.assertEqual(guard.credential('own-pod'),'runtime-only-secret')
            for invalid in ('other-pod','../other'):
                with self.assertRaises(ValueError):guard.credential(invalid)
    def test_deadline_requests_stop_only_for_own_pod_and_never_records_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'guard.json';clock=[1000.0]
            def sleep(n):clock[0]+=n
            request=Mock(side_effect=['RUNNING','RUNNING','EXITED','EXITED'])
            with patch.object(guard,'credential',return_value='runtime-only-secret'),patch.object(guard,'request',request), \
                 patch.object(guard.time,'time',side_effect=lambda:clock[0]),patch.object(guard.time,'sleep',side_effect=sleep):
                guard.run('own-pod',1001,marker)
            stops=[call for call in request.call_args_list if call.kwargs.get('stop')]
            self.assertEqual(len(stops),1);self.assertEqual(stops[0].args[0],'own-pod')
            self.assertNotIn('secret',marker.read_text());self.assertEqual(json.loads(marker.read_text())['state'],'stop_requested')
    def test_excessive_deadline_never_arms(self):
        with patch.object(guard,'credential',return_value='runtime-only-secret'),patch.object(guard,'request') as request:
            with self.assertRaises(ValueError):guard.run('own-pod',guard.time.time()+1000,Path('/unused'))
            request.assert_not_called()


if __name__=='__main__':unittest.main()
