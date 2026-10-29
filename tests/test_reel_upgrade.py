import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import sys
import types
from unittest.mock import patch

import instagram_reel_media as media
import instagram_reel_usage as usage
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
import instagram_manual_news_intake as intake

class UsageTests(unittest.TestCase):
    def test_price_range_and_unknown(self):
        calls=[('deepseek-flash',1000,2000,300,1)]
        self.assertEqual(tuple(map(str,usage.estimate(calls,now=1793270000))),('0.000483','0.000966'))
        self.assertIsNone(usage.estimate([('deepseek-flash',None,None,None,0)],now=1793270000))
        self.assertIsNone(usage.estimate(calls,now=1795910400))

    def test_notice_is_retried_then_sent_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state'; sent=[]
            with patch.object(usage,'STATE',state),patch.object(usage,'DB',state/'usage.sqlite3'):
                @usage.tracked('admin_link')
                def job():
                    usage.record_envelope({'model':'deepseek-flash'}, {'usage':{'prompt_tokens':15,'prompt_cache_hit_tokens':5,'prompt_cache_miss_tokens':10,'completion_tokens':4,'total_tokens':19}})
                    return 'prepared'
                job()
                def fail(*args): raise OSError('temporary')
                with patch.object(usage.time,'time',return_value=1793270000):
                    usage.deliver_notices('secret',{123},fail)
                    usage.deliver_notices('secret',{123},lambda *a: sent.append(a))
                    usage.deliver_notices('secret',{123},lambda *a: sent.append(a))
                self.assertEqual(len(sent),1)
                self.assertIn('تخمین',sent[0][2])
    def test_success_failure_and_unknown_do_not_store_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state'
            with patch.object(usage,'STATE',state),patch.object(usage,'DB',state/'usage.sqlite3'):
                @usage.tracked('admin_link')
                def job(fail=False):
                    usage.record_envelope({'model':'test-model','messages':['private text']},{'usage':{'prompt_tokens':15,'prompt_cache_hit_tokens':5,'prompt_cache_miss_tokens':10,'completion_tokens':4,'total_tokens':19}})
                    usage.record_envelope({'model':'test-model'}, {})
                    if fail: raise ValueError('private article text')
                    return 'prepared'
                self.assertEqual(job(),'prepared')
                with self.assertRaises(ValueError): job(True)
                with sqlite3.connect(state/'usage.sqlite3') as con:
                    self.assertEqual(con.execute('select count(*) from calls').fetchone()[0],4)
                    self.assertEqual(con.execute('select count(*) from calls where usage_known=0').fetchone()[0],2)
                    self.assertEqual(con.execute("select count(*) from runs where outcome='failed' and error_type='ValueError'").fetchone()[0],1)
                con.close()
                self.assertNotIn(b'private article text',(state/'usage.sqlite3').read_bytes())

class MediaTests(unittest.TestCase):
    def test_only_approved_matching_pinned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=b'x'*1200; (root/'image.jpg').write_bytes(data)
            item={'approved':True,'illustrative':True,'keywords':['bitcoin'],'file':'image.jpg','license':'CC BY 4.0','author':'Creator','source_url':'https://example.org/photo','sha256':hashlib.sha256(data).hexdigest()}
            (root/'manifest.json').write_text(json.dumps([item]),encoding='utf-8')
            selected=media.select({'title_original':'Bitcoin market','title_fa':''},root)
            self.assertEqual(len(selected),1)
            self.assertIn('CC BY 4.0',media.caption(selected))
            self.assertEqual(media.select({'title_original':'Other markets','title_fa':''},root),[])
            (root/'image.jpg').write_bytes(b'y'*1200)
            self.assertEqual(media.select({'title_original':'Bitcoin','title_fa':''},root),[])
            item['file']='../image.jpg'; (root/'manifest.json').write_text(json.dumps([item]))
            self.assertEqual(media.select({'title_original':'Bitcoin','title_fa':''},root),[])

class TrialFilterTests(unittest.TestCase):
    def test_forecast_can_pass_trial_without_weakening_feed(self):
        assessment={'story_type':'forecast','certainty':'unknown','relevance':{'points':0},'usefulness':{'points':0}}
        engine=types.SimpleNamespace(grade=lambda *args:[{'assessment':assessment}])
        ranked=types.SimpleNamespace(configure_engine=lambda kind:None)
        self.assertEqual(intake.classify(engine,ranked,None,{},0,trial_relaxed=True)[0],'crypto')
        with self.assertRaises(intake.IntakeError): intake.classify(engine,ranked,None,{},0)

if __name__=='__main__': unittest.main()

