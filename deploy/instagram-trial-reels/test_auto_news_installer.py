#!/usr/bin/env python3
"""Exercise automatic-news installer and rollback only in temporary directories."""
import hashlib
import importlib.util
import io
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
    fcntl=types.ModuleType('fcntl')
    fcntl.LOCK_EX,fcntl.LOCK_NB=1,2
    fcntl.flock=lambda *args: None
    sys.modules['fcntl']=fcntl

path=Path(__file__).with_name('activate_auto_news_images.py')
spec=importlib.util.spec_from_file_location('auto_image_installer',path)
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='auto-installer-test-', dir=Path.cwd())
        self.home=Path(self.temp.name)
        self.revision='f'*40
        self.runtime=self.home/'.local/state/kiani-instagram-manual-news/source'/self.revision
        self.old=self.home/'kiani-instagram-ranked-news-releases'/installer.BASE
        self.meta=self.home/'.local/state/kiani-instagram-insights/activation.json'
        self.assets=self.home/'kiani-instagram-publisher'
        self.repo=self.home/'telegram_bot_repo'
        self.repo.mkdir()
        for name in installer.OLD_FILES:
            file=self.old/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(('old:'+name).encode())
        for name in installer.EXTRA:
            file=self.runtime/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(('extra:'+name).encode())
        for name in ('deploy/instagram-trial-reels/automatic_ranked_news_images.py',
                     'deploy/instagram-trial-reels/check_auto_news_images.py',
                     'selector_trial_runtime/instagram_news_renderer.py'):
            file=self.runtime/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(('new:'+name).encode())
        for name in installer.ASSETS:
            file=self.assets/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(('asset:'+name).encode())
        config=dict(news_runtime_revision=installer.BASE,hourly_news_enabled=True,
                    news_schedule=dict(per_slot=1,per_category_day=10),
                    policy=dict(assessment_hours=2,keep_at_or_above_views=200),
                    news_source_hashes={n:hashlib.sha256((self.old/n).read_bytes()).hexdigest() for n in installer.OLD_FILES})
        self.meta.parent.mkdir(parents=True,exist_ok=True)
        self.meta.write_text(json.dumps(config))
        ref=str(self.old/'instagram_ranked_news.py')
        self.crypto=self.home/'publish-kiani-instagram-news.sh'
        self.economy=self.home/'publish-kiani-instagram-economy.sh'
        self.crypto.write_text('exec '+ref+' --publish\n')
        self.economy.write_text('exec '+ref+' --collect-only\nexec '+ref+' --publish\n')
        self.before={p:p.read_bytes() for p in (self.meta,self.crypto,self.economy)}
        self.cron=b'unchanged schedule\n'

    def tearDown(self): self.temp.cleanup()

    def invoke(self, fail_second_wrapper=False):
        def get_output(command,**kwargs):
            if command[:2]==['crontab','-l']: return self.cron
            if command[0]=='git': return (self.old/command[-1].split(':',1)[1]).read_bytes()
            raise AssertionError(command)
        original_atomic=installer.atomic
        failures=[0]
        def atomic(target,data,mode=0o600):
            if fail_second_wrapper and target==self.economy and not failures[0]:
                failures[0]+=1
                raise OSError('simulated write failure')
            return original_atomic(target,data,mode)
        args=['installer','--runtime',str(self.runtime),'--revision',self.revision,'--repo',str(self.repo),'--install']
        owner=self.old.stat().st_uid
        with patch.object(Path,'home',return_value=self.home), patch.object(sys,'argv',args), \
             patch.object(installer.os,'geteuid',return_value=1000,create=True), \
             patch.object(installer.os,'getuid',return_value=owner,create=True), \
             patch.object(installer.subprocess,'check_output',side_effect=get_output), \
             patch.object(installer.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)), \
             patch.object(installer,'preview'), patch.object(installer,'atomic',side_effect=atomic), \
             patch.object(sys,'stdout',new_callable=io.StringIO):
            return installer.main()

    def test_only_wrappers_and_news_metadata_change(self):
        self.invoke()
        meta=json.loads(self.meta.read_text())
        self.assertEqual(meta['news_runtime_revision'],self.revision)
        self.assertEqual(meta['policy']['keep_at_or_above_views'],200)
        self.assertIn(self.revision,self.crypto.read_text())
        self.assertEqual(self.economy.read_text().count(self.revision),2)
        self.assertEqual(self.cron,b'unchanged schedule\n')

    def test_partial_switch_rolls_back(self):
        with self.assertRaises(OSError): self.invoke(fail_second_wrapper=True)
        for path,raw in self.before.items(): self.assertEqual(path.read_bytes(),raw)

    def test_changed_original_release_stops_before_switch(self):
        (self.old/'crypto_news_trial.py').write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.invoke()
        for path,raw in self.before.items(): self.assertEqual(path.read_bytes(),raw)

if __name__=='__main__': unittest.main()

