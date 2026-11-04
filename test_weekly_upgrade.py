"""Installation checks using isolated local state, never production files."""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    import fcntl
except ImportError:
    fcntl = types.ModuleType('fcntl')
    fcntl.LOCK_EX, fcntl.LOCK_NB = 1, 2
    fcntl.flock = lambda *args: None
    sys.modules['fcntl'] = fcntl
import upgrade_weekly_pair as upgrade

class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.state = self.home/'.local/state/kiani-instagram-weekly-markets'
        self.state.mkdir(parents=True)
        self.base = self.home/'kiani-instagram-weekly-markets-releases'/upgrade.BASE
        self.rev = 'a'*40
        self.original = {name:('old:'+name).encode() for name in upgrade.FILES}
        self.candidate = dict(self.original, weekly_market_data_py=b'')
        self.candidate.pop('weekly_market_data_py')
        self.candidate['weekly_market_data.py']=b'updated adapter'
        for name, raw in self.original.items():
            path=self.base/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
        self.meta=self.state/'activation.json'
        self.meta.write_text(json.dumps({'revision':upgrade.BASE,'runtime_hash':upgrade.fingerprint(self.original)}))
        self.launcher=self.home/'publish-kiani-instagram-weekly-markets.sh'
        self.before_launcher=('exec '+str(self.base/'instagram_weekly_markets.py')+' --scheduled\n').encode()
        self.launcher.write_bytes(self.before_launcher)
        self.cron=b'unchanged scheduler\n'
        def blob(repo, rev, name):
            if name in upgrade.CHECKS: return b'fixture'
            return self.original[name] if rev==upgrade.BASE else self.candidate[name]
        self.patches = [patch.object(Path,'home',return_value=self.home),
                        patch.object(upgrade,'blob',side_effect=blob),
                        patch.object(upgrade.subprocess,'check_output',return_value=self.cron),
                        patch.object(sys,'argv',['upgrade','--revision',self.rev,'--install']),
                        patch.object(upgrade.os,'geteuid',return_value=1000,create=True),
                        patch.object(upgrade.os,'getuid',return_value=self.meta.stat().st_uid,create=True)]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def test_install_preserves_history_and_schedule(self):
        history=self.state/'markets.sqlite3'; history.write_bytes(b'preserve')
        upgrade.main()
        config=json.loads(self.meta.read_text())
        self.assertEqual(config['revision'],self.rev)
        self.assertEqual(config['runtime_hash'],upgrade.fingerprint(self.candidate))
        self.assertIn(self.rev.encode(),self.launcher.read_bytes())
        self.assertEqual(history.read_bytes(),b'preserve')

    def test_unexpected_installed_source_aborts_without_switching(self):
        (self.base/'weekly_market_data.py').write_bytes(b'tampered')
        before=self.meta.read_bytes()
        with self.assertRaises(RuntimeError): upgrade.main()
        self.assertEqual(self.meta.read_bytes(),before)
        self.assertEqual(self.launcher.read_bytes(),self.before_launcher)

if __name__ == '__main__': unittest.main()

