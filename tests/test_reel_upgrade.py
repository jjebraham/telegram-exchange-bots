import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import sys
import types
import time
from unittest.mock import patch

import instagram_reel_media as media
import instagram_reel_usage as usage
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
import instagram_manual_news_intake as intake
ROOT = Path(__file__).parent if (Path(__file__).parent/'selector_trial_runtime').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'selector_trial_runtime'))
sys.path.insert(0, str(ROOT.parent/'news-python-libs'))
import crypto_news_trial as engine
import instagram_trial_reels as reels

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
    def test_five_admin_limit_counts_reservations_not_failed_or_auto(self):
        con=sqlite3.connect(':memory:')
        con.execute('CREATE TABLE trial_reels(posted_day TEXT, origin TEXT, status TEXT)')
        for status in ('published','published','failed','needs_review','rendering'):
            con.execute('INSERT INTO trial_reels VALUES(?,?,?)',('2026-10-29','admin_link',status))
        con.execute('INSERT INTO trial_reels VALUES(?,?,?)',('2026-10-29','daily_top_story','published'))
        con.execute('INSERT INTO trial_reels VALUES(?,?,?)',('2026-10-28','admin_link','published'))
        reels._enforce_daily_limit(con,'admin_link','2026-10-29')
        con.execute('INSERT INTO trial_reels VALUES(?,?,?)',('2026-10-29','admin_link','publishing'))
        with self.assertRaises(reels.TrialReelError): reels._enforce_daily_limit(con,'admin_link','2026-10-29')
        with self.assertRaises(reels.TrialReelError): reels._enforce_daily_limit(con,'daily_top_story','2026-10-29')
        reels._enforce_daily_limit(con,'admin_link','2026-10-30')
        con.close()
    def test_admin_unknown_or_old_date_bypasses_only_trial_freshness(self):
        now=time.time()
        self.assertTrue(reels._article_allowed('admin_link',0,now))
        self.assertTrue(reels._article_allowed('admin_link',now-300000,now))
        self.assertFalse(reels._article_allowed('daily_top_story',0,now))
        self.assertFalse(reels._article_allowed('admin_link',float('nan'),now))

    def test_previous_feed_submission_does_not_block_trial(self):
        con=sqlite3.connect(':memory:')
        con.row_factory=sqlite3.Row
        con.execute('CREATE TABLE submissions(source_key TEXT, update_id INTEGER, status TEXT, media_id TEXT, request_type TEXT, received_at REAL)')
        con.execute("INSERT INTO submissions VALUES('key',1,'published','media','feed',1)")
        self.assertIsNone(intake.recent_trial_duplicate(con,'key',2))
        con.execute("INSERT INTO submissions VALUES('key',3,'trial_published','media','trial',2)")
        self.assertIsNotNone(intake.recent_trial_duplicate(con,'key',2))
        con.close()
    def test_forecast_can_pass_trial_without_weakening_feed(self):
        assessment={'story_type':'forecast','certainty':'unknown','relevance':{'points':0},'usefulness':{'points':0}}
        engine=types.SimpleNamespace(grade=lambda *args:[{'assessment':assessment}])
        ranked=types.SimpleNamespace(configure_engine=lambda kind:None)
        self.assertEqual(intake.classify(engine,ranked,None,{},0,trial_relaxed=True)[0],'crypto')
        with self.assertRaises(intake.IntakeError): intake.classify(engine,ranked,None,{},0)

    def test_admin_undated_article_does_not_weaken_standard_source_check(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def geturl(self): return 'https://decrypt.co/story'
            def read(self,n): return b'<html></html>'
        class Dates:
            def __init__(self,*args): self.dates=[]
            def feed(self,*args): pass
        class Parser:
            def __init__(self): self.article_parts=['A source passage with sufficient detail. '*10]; self.parts=[]; self.meta={'og:title':'A news story'}
            def feed(self,*args): pass
        opener=types.SimpleNamespace(open=lambda *a,**k:Response())
        item={'id':'1','source_url':'https://decrypt.co/story','title_original':'','source_name':''}
        with patch.object(engine,'build_opener',return_value=opener),patch.object(engine,'Dates',Dates),patch.object(engine,'ArticleParser',Parser):
            with self.assertRaises(engine.NewsError): engine.source_material(item,time.time())
            result=engine.source_material(item,time.time(),admin_override=True)
            self.assertEqual(result['article_published_at'],0)
            self.assertEqual(result['article_date'],'')

if __name__=='__main__': unittest.main()

