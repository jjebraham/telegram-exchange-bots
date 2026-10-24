#!/usr/bin/env python3
"""Daily 20:00 Tehran observations; one Thursday weekly market-comparison Feed."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

import weekly_market_data as data
from weekly_market_data import GoldError, TEHRAN, UTC, stamp
from instagram_economic_calendar_renderer import labels
import instagram_weekly_markets_renderer as renderer

STATE=Path.home()/'.local/state/kiani-instagram-weekly-markets'
PUBLIC=Path('/var/www/peerexo.com/public/instagram-rates')
BASE='https://peerexo.com/instagram-rates'
FILES=('weekly_market_data.py','instagram_weekly_markets.py','instagram_weekly_markets_renderer.py',
       'iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py','economic_calendar_data.py',
       'instagram_economic_calendar_renderer.py','assets/instagram/gold-coin.png','assets/instagram/gold-bars.png')
ASSETS=('fonts/Vazirmatn-Regular.ttf','fonts/Vazirmatn-Bold.ttf','assets/instagram/kiani-logo.svg')


def fingerprint(root,names=FILES):
    return hashlib.sha256(b'\0'.join(n.encode()+b'\0'+(Path(root)/n).read_bytes() for n in names)).hexdigest()


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink(): raise GoldError('Refusing a symlink lock.')
    with path.open('a') as handle:
        path.chmod(0o600)
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise GoldError('Another weekly-market worker is active.') from None
        yield


def database(path):
    if path.is_symlink(): raise GoldError('Refusing a symlink state database.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    con=sqlite3.connect(path,timeout=15); path.chmod(0o600); con.row_factory=sqlite3.Row
    con.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS observations (
            anchor TEXT PRIMARY KEY, created_at REAL NOT NULL, snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL, runtime_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preflights (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, snapshot_json TEXT NOT NULL,
            runtime_hash TEXT NOT NULL, assets_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS instagram_news_publications (
            week_key TEXT PRIMARY KEY,status TEXT NOT NULL,started_at REAL NOT NULL,
            finished_at REAL,container_id TEXT,media_id TEXT,manifest_json TEXT NOT NULL,error_type TEXT);
    ''')
    return con


def daily_anchor(now):
    return now.astimezone(TEHRAN).replace(hour=20,minute=0,second=0,microsecond=0).astimezone(UTC)


def next_thursday(now):
    local=now.astimezone(TEHRAN); start=local.replace(hour=20,minute=0,second=0,microsecond=0)
    start+=timedelta(days=(3-local.weekday())%7)
    return start if start>local else start+timedelta(days=7)


def observation(con,anchor):
    row=con.execute('SELECT * FROM observations WHERE anchor=?',(anchor.isoformat(),)).fetchone()
    if not row: return None
    snapshot=json.loads(row['snapshot_json'])
    if data.digest(snapshot)!=row['snapshot_hash'] or stamp(snapshot['anchor'])!=anchor:
        raise GoldError('Saved weekly observation hash/anchor differs; review the private state.')
    data.validate(snapshot)
    return snapshot


def remember(con,snapshot,root):
    data.validate(snapshot,live=True)
    anchor=stamp(snapshot['anchor']); now=datetime.now(UTC)
    if anchor!=daily_anchor(now) or not 0<=(now-anchor).total_seconds()<900:
        raise GoldError('Only an observation from today’s 20:00–20:15 window may enter history.')
    existing=observation(con,anchor)
    if existing: return existing  # Never overwrite the frozen first verified daily endpoint.
    with con:
        con.execute('INSERT INTO observations VALUES (?,?,?,?,?)',
                    (anchor.isoformat(),time.time(),data.canonical(snapshot),data.digest(snapshot),fingerprint(root)))
    return snapshot


def current_comparison(con,anchor):
    current=observation(con,anchor); previous=observation(con,anchor-timedelta(days=7))
    if not current or not previous: return None
    return data.compare(previous,current)


def helper(assets):
    spec=importlib.util.spec_from_file_location('kiani_weekly_markets_graph',assets/'instagram_daily_rates.py')
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
    return module


def duplicate(con,key):
    row=con.execute('SELECT * FROM instagram_news_publications WHERE week_key=?',(key,)).fetchone()
    if row and row['status']=='published':
        print('Weekly comparison already published:',row['media_id'],flush=True); return True
    if row and row['status'] in {'preparing','publishing','needs_review'}:
        raise GoldError('An earlier weekly publication requires review; no blind duplicate.')
    return False


def publication_check(con,comparison,manifest):
    now=datetime.now(TEHRAN); anchor=daily_anchor(now)
    if now.weekday()!=3 or not 0<=(now.astimezone(UTC)-anchor).total_seconds()<1200:
        raise GoldError('Weekly publication is allowed only Thursday 20:00–20:20 Tehran.')
    expected=current_comparison(con,anchor)
    if not expected or data.canonical(expected)!=data.canonical(comparison):
        raise GoldError('Rendered weekly returns differ from immutable verified history.')
    if comparison.get('layout_sample') or manifest.get('publication_mode')!='scheduled':
        raise GoldError('A sample/preview cannot be published.')
    if manifest.get('comparison_hash')!=data.digest(comparison) or manifest.get('caption')!=renderer.caption(expected):
        raise GoldError('Weekly caption/manifest differs from verified returns.')
    images=manifest.get('images',[]); urls=manifest.get('image_urls',[])
    if len(images)!=1 or len(urls)!=1:
        raise GoldError('Expected exactly one weekly comparison slide.')
    path=Path(images[0]).resolve()
    if not path.is_relative_to(PUBLIC/'weekly-markets') or path.suffix!='.jpg' or urls[0]!=BASE+'/weekly-markets/'+path.name:
        raise GoldError('Weekly image is outside the configured public directory.')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest.get('image_sha256'):
        raise GoldError('Weekly rendered image changed.')


def quota(graph):
    response=graph._graph_request('/content_publishing_limit','GET',{'fields':'quota_usage,config'})
    rows=response.get('data')
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        raise GoldError('Publishing quota is unavailable.')
    used=rows[0].get('quota_usage'); total=rows[0].get('config',{}).get('quota_total')
    if type(used)!=int or type(total)!=int or used<0 or total-used<2:
        raise GoldError('Publishing quota cannot cover the weekly Feed and its Story.')


def publish(con,comparison,manifest,assets):
    publication_check(con,comparison,manifest)
    key=stamp(comparison['window_end']).astimezone(TEHRAN).date().isoformat()
    if duplicate(con,key): return
    if not os.getenv('INSTAGRAM_ACCESS_TOKEN') or not re.fullmatch('[0-9]+',os.getenv('INSTAGRAM_USER_ID','')):
        raise GoldError('Existing private Instagram credentials are not loaded.')
    graph=helper(assets); quota(graph); graph.verify_public_image(manifest['image_urls'][0])
    with con:
        con.execute('''INSERT INTO instagram_news_publications(week_key,status,started_at,manifest_json)
            VALUES (?,'preparing',?,?) ON CONFLICT(week_key) DO UPDATE SET status='preparing',
            started_at=excluded.started_at,finished_at=NULL,container_id=NULL,media_id=NULL,
            manifest_json=excluded.manifest_json,error_type=NULL''',(key,time.time(),data.canonical(manifest)))
    final_started=False
    try:
        parent=graph._create_container({'image_url':manifest['image_urls'][0],'caption':manifest['caption']})
        if not re.fullmatch('[0-9]+',str(parent)): raise GoldError('Invalid weekly Meta container ID.')
        with con: con.execute('UPDATE instagram_news_publications SET container_id=? WHERE week_key=?',(str(parent),key))
        graph._wait_for_container(parent)
        publication_check(con,comparison,manifest)
        quota(graph)
        with con: con.execute("UPDATE instagram_news_publications SET status='publishing' WHERE week_key=?",(key,))
        final_started=True
        media=graph._publish_container(parent)
        if not re.fullmatch('[0-9]+',str(media)): raise GoldError('Invalid weekly Meta media ID.')
        with con:
            con.execute("UPDATE instagram_news_publications SET status='published',media_id=?,finished_at=? WHERE week_key=?",(str(media),time.time(),key))
        print('Published weekly market comparison:',media,flush=True)
    except BaseException as exc:
        with con:
            con.execute('UPDATE instagram_news_publications SET status=?,finished_at=?,error_type=? WHERE week_key=?',
                        ('needs_review' if final_started else 'failed',time.time(),type(exc).__name__,key))
        raise


def layout_sample():
    end=next_thursday(datetime.now(TEHRAN)); values={'btc':'6.40','emami':'4.80','gold18':'3.20','usd':'1.50','eth':'-2.10'}
    return dict(version=data.VERSION,unit='toman',layout_sample=True,window_start=(end-timedelta(days=7)).isoformat(),
                window_end=end.isoformat(),rows=[dict(id=k,name=data.KINDS[k],change_pct=v,display_pct=v) for k,v in values.items()])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--scheduled',action='store_true')
    action.add_argument('--layout-preview',action='store_true')
    action.add_argument('--status',action='store_true')
    parser.add_argument('--asset-root',type=Path,default=Path.home()/'kiani-instagram-publisher')
    parser.add_argument('--state',type=Path,default=STATE)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(); os.umask(0o077)
    root=Path(__file__).resolve().parent; labels(datetime.now(TEHRAN),args.asset_root)
    if args.scheduled and (args.state.resolve()!=STATE.resolve() or args.output or args.asset_root.resolve()!=(Path.home()/'kiani-instagram-publisher').resolve()):
        raise GoldError('Scheduled publishing uses only the installed private state and media directory.')
    if args.layout_preview:
        output=args.output or PUBLIC/'weekly-markets-preview'
        for image in renderer.render(layout_sample(),output,args.asset_root,preview=True): print('Layout sample:',image,flush=True)
        print('FICTIONAL layout only. No source history, Instagram contact or schedule change.'); return 0
    with locked(args.state/'publication.lock'):
        con=database(args.state/'markets.sqlite3')
        try:
            now=datetime.now(TEHRAN); anchor=daily_anchor(now)
            if args.status:
                print('Now:',now.isoformat()); print('Verified snapshots:',con.execute('SELECT count(*) FROM observations').fetchone()[0])
                print('Next weekly slot:',next_thursday(now).isoformat())
                print('Publication states:',dict(con.execute('SELECT status,count(*) FROM instagram_news_publications GROUP BY status')))
                return 0
            if args.scheduled and not 0<=(now.astimezone(UTC)-anchor).total_seconds()<900:
                print('Outside daily 20:00–20:15 Tehran collection window; no catch-up.'); return 0
            if args.scheduled and now.weekday()==3 and duplicate(con,anchor.astimezone(TEHRAN).date().isoformat()): return 0
            folder=args.state/'runs'/(now.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8])
            folder.mkdir(parents=True,mode=0o700)
            snapshot=observation(con,anchor) if args.scheduled else None
            if snapshot is None:
                snapshot=data.collect(anchor if args.scheduled else None)
                (folder/'source.json').write_text(data.canonical(snapshot),encoding='utf-8')
                print('Source health:',json.dumps(snapshot['health'],ensure_ascii=False),flush=True)
                if snapshot.get('status')!='verified':
                    print('SKIPPED weekly comparison:',snapshot.get('reason'),flush=True)
                    print('Private audit:',folder/'source.json',flush=True)
                    return 0 if args.scheduled else 1
                data.validate(snapshot,live=True)
                if args.scheduled: snapshot=remember(con,snapshot,root)
            print('Verified current prices (TOMAN):',json.dumps([{k:r[k] for k in ('id','price','sources','agreement_pct')} for r in snapshot['rows']],ensure_ascii=False),flush=True)
            if not args.scheduled:
                with con:
                    con.execute('INSERT INTO preflights VALUES (?,?,?,?,?)',
                                (folder.name,time.time(),data.canonical(snapshot),fingerprint(root),fingerprint(args.asset_root,ASSETS)))
                print('Live preflight passed; no historical prices invented and no Instagram contact.')
                print('Private audit:',folder/'source.json'); return 0
            print('Frozen verified observation:',anchor.astimezone(TEHRAN).isoformat(),flush=True)
            if now.weekday()!=3:
                print('Daily history captured. Feed posts only on Thursday.'); return 0
            comparison=current_comparison(con,anchor)
            if comparison is None:
                print('WARMING UP: matching Thursday observation from seven days earlier is missing; no post.')
                print('Earliest comparison using this baseline:',(anchor+timedelta(days=7)).astimezone(TEHRAN).isoformat()); return 0
            output=PUBLIC/'weekly-markets'; output.mkdir(parents=True,exist_ok=True,mode=0o755); output.chmod(0o755)
            images=renderer.render(comparison,output,args.asset_root)
            manifest=dict(kind='weekly_markets',publication_mode='scheduled',timezone='Asia/Tehran',images=images,
                image_urls=[BASE+'/weekly-markets/'+Path(p).name for p in images],caption=renderer.caption(comparison),
                comparison_hash=data.digest(comparison),image_sha256=hashlib.sha256(Path(images[0]).read_bytes()).hexdigest(),
                window_start=comparison['window_start'],window_end=comparison['window_end'])
            if len(manifest['caption'])>2200: raise GoldError('Weekly caption exceeds Instagram capacity.')
            (folder/'comparison.json').write_text(data.canonical(dict(comparison=comparison,manifest=manifest)),encoding='utf-8')
            publish(con,comparison,manifest,args.asset_root)
            print('Private comparison audit:',folder/'comparison.json',flush=True)
            return 0
        finally: con.close()


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Weekly markets stopped:',str(exc) if isinstance(exc,GoldError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
