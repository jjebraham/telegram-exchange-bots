"""Installer rollback tests in a temporary fake publisher home."""
import hashlib
import importlib.util
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

folder = Path(__file__).parent
spec = importlib.util.spec_from_file_location('fallback_installer', folder / 'upgrade_auto_news_fallback.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fallback-installer-test-', dir=Path.cwd())
        self.home = Path(self.temp.name)
        self.old = self.home / 'kiani-instagram-ranked-news-releases' / installer.BASE
        self.repo = self.home / 'repo'
        self.repo.mkdir()
        self.revision = 'f' * 40
        self.originals = {}
        for name in installer.FILES:
            raw = ('old:' + name).encode()
            self.originals[name] = raw
            path = self.old / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.meta = self.home / '.local/state/kiani-instagram-insights/activation.json'
        self.meta.parent.mkdir(parents=True)
        self.meta.write_text(json.dumps({
            'news_runtime_revision': installer.BASE, 'hourly_news_enabled': True,
            'news_source_hashes': {n: hashlib.sha256(b).hexdigest() for n, b in self.originals.items()},
            'news_template': {'runtime_hash': installer.fingerprint(self.originals)},
            'news_schedule': {'per_slot': 1}, 'policy': {'keep_at_or_above_views': 200},
        }))
        ref = str(self.old / 'instagram_ranked_news.py')
        self.crypto = self.home / 'publish-kiani-instagram-news.sh'
        self.economy = self.home / 'publish-kiani-instagram-economy.sh'
        self.crypto.write_text(ref + ' --publish\n')
        self.economy.write_text(ref + ' --collect\n' + ref + ' --publish\n')
        self.before = {p: p.read_bytes() for p in (self.meta, self.crypto, self.economy)}

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, fail_second=False):
        real_atomic = installer.atomic
        failed = [False]

        def atomic(path, data, mode=0o600):
            if fail_second and path == self.economy and not failed[0]:
                failed[0] = True
                raise OSError('simulated write failure')
            return real_atomic(path, data, mode)

        def source(repo, revision, name):
            if revision == installer.BASE:
                return self.originals['instagram_ranked_news.py' if name == installer.WORKER else name]
            if name == installer.WORKER:
                return (folder / 'automatic_ranked_news_images.py').read_bytes()
            if name == installer.TEST:
                return (folder / 'test_news_image_fallback.py').read_bytes()
            raise AssertionError(name)

        args = ['installer', '--repo', str(self.repo), '--revision', self.revision, '--install']
        with patch.object(Path, 'home', return_value=self.home), patch.object(sys, 'argv', args), \
             patch.object(installer.os, 'geteuid', return_value=1000, create=True), \
             patch.object(installer.os, 'getuid', return_value=self.old.stat().st_uid, create=True), \
             patch.object(installer, 'git_file', side_effect=source), \
             patch.object(installer.subprocess, 'run'), \
             patch.object(installer.subprocess, 'check_output', return_value=b'unchanged cron\n'), \
             patch.object(installer, 'atomic', side_effect=atomic):
            installer.main()

    def test_success_preserves_schedule_and_policy(self):
        self.invoke()
        meta = json.loads(self.meta.read_text())
        self.assertEqual(meta['news_runtime_revision'], self.revision)
        self.assertEqual(meta['policy']['keep_at_or_above_views'], 200)
        self.assertEqual(meta['news_schedule']['per_slot'], 1)
        self.assertIn(self.revision, self.crypto.read_text())
        self.assertEqual(self.economy.read_text().count(self.revision), 2)

    def test_failed_switch_rolls_back_both_wrappers_and_metadata(self):
        with self.assertRaises(OSError):
            self.invoke(fail_second=True)
        for path, contents in self.before.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_changed_release_stops_before_switch(self):
        (self.old / 'instagram_news_batch.py').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            self.invoke()
        for path, contents in self.before.items():
            self.assertEqual(path.read_bytes(), contents)


if __name__ == '__main__':
    unittest.main()
