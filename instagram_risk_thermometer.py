#!/usr/bin/env python3
"""Sunday 18:00 Tehran free-data carousel; Friday 17:00 New York spot history."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime,timedelta
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

import risk_market_core as core
import risk_market_sources as sources
import instagram_risk_renderer as renderer

STATE=Path.home()/'.local/state/kiani-instagram-risk-thermometer'
PUBLIC=Path('/var/www/peerexo.com/public/instagram-rates')
BASE='https://peerexo.com/instagram-rates'
ASSETS=('fonts/Vazirmatn-Regular.ttf','fonts/Vazirmatn-Bold.ttf','assets/instagram/kiani-logo.svg','instagram_daily_rates.py')
FILES=('risk_market_core.py','risk_market_sources.py','instagram_risk_renderer.py','instagram_risk_thermometer.py',
       'global_metals_data.py','iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py',
       'economic_calendar_data.py','instagram_economic_calendar_renderer.py','instagram_news_batch.py',
       'instagram_insights_data.py')


def fingerprint(root,names=FILES):
    return hashlib.sha256(b'\0'.join(n.encode()+b'\0'+(Path(root)/n).read_bytes() for n in names)).hexdigest()


def save(path,value):
    path=Path(path)
    if path.is_symlink() or path.exists():
        raise core.RiskError('Audit target already exists.')
    path.write_text(core.canonical(value),encoding='utf-8');path.chmod(0o600)


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink(): raise core.RiskError('Refusing a symlink lock.')
    with path.open('a') as handle:
        path.chmod(0o600)
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise core.RiskError('Risk worker already active.') from None
        yield


def database(path):
    if path.is_symlink(): raise core.RiskError('Refusing a symlink state database.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    con=sqlite3.connect(path,timeout=15);con.row_factory=sqlite3.Row;path.chmod(0o600)
    con.executescript('''PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS endpoints(asset TEXT,session_date TEXT,endpoint_json TEXT NOT NULL,
        endpoint_hash TEXT NOT NULL,runtime_hash TEXT NOT NULL,PRIMARY KEY(asset,session_date));
      CREATE TABLE IF NOT EXISTS preflights(id TEXT PRIMARY KEY,created_at REAL NOT NULL,
        runtime_hash TEXT NOT NULL,assets_hash TEXT NOT NULL,report_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS instagram_news_publications(week_key TEXT PRIMARY KEY,status TEXT NOT NULL,
        started_at REAL NOT NULL,finished_at REAL,container_id TEXT,media_id TEXT,manifest_json TEXT NOT NULL,error_type TEXT);
    ''')
    return con


def run_folder(state):
    folder=state/'runs'/(datetime.now(core.UTC).strftime('%Y%m%dT%H%M%S-')+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,mode=0o700);return folder


def grouped(quotes):
    groups={};result={};rejected=[]
    for q in quotes: groups.setdefault((q['asset'],q['session_date']),[]).append(q)
    for (asset,session),rows in sorted(groups.items()):
        try: result.setdefault(asset,{})[session]=core.corroborate(rows,asset,session)
        except core.RiskError as exc: rejected.append(dict(asset=asset,date=session,reason=str(exc)))
    for asset in core.ASSETS:
        common=sorted(d for (a,d),rows in groups.items() if a==asset and len({q['provider'] for q in rows})>=2)
        if common and common[-1] not in result.get(asset,{}):
            result.pop(asset,None)  # A conflict may not be hidden by choosing an older agreeing date.
            rejected.append(dict(asset=asset,date=common[-1],reason='Latest common-date evidence conflicts; no fallback.'))
    return result,rejected


def spot_history(con,state):
    result={}
    end=core.report_friday()
    for row in con.execute('SELECT * FROM endpoints WHERE session_date BETWEEN ? AND ?',
                           ((end-timedelta(days=7)).isoformat(),end.isoformat())):
        if row['asset'] not in core.SPOT:
            raise core.RiskError('Only frozen spot captures may enter local history.')
        endpoint=json.loads(row['endpoint_json'])
        if core.digest(endpoint)!=row['endpoint_hash']:
            raise core.RiskError('Frozen endpoint hash differs.')
        core.validate_endpoint(endpoint,row['asset'],row['session_date'])
        sources.verify_evidence(endpoint,state/'runs')
        result.setdefault(row['asset'],{})[row['session_date']]=endpoint
    return result


def collect(con,state,folder):
    quotes,health=sources.public_sources(folder)
    endpoints,rejected=grouped(quotes)
    endpoints.update(spot_history(con,state))
    try:
        comparison=core.compare(endpoints,core.report_friday().isoformat());reason=None
    except core.RiskError as exc: comparison=None;reason=str(exc)
    report=dict(version=core.VERSION,created_at=datetime.now(core.UTC).isoformat(),health=health,
                endpoints=endpoints,rejected=rejected,comparison=comparison,hold_reason=reason)
    save(folder/'source.json',report)
    return report


def capture(con,state,folder,root):
    endpoints,health=sources.capture_spots(folder)
    for asset,endpoint in endpoints.items():
        core.validate_endpoint(endpoint,asset,endpoint['session_date'])
        sources.verify_evidence(endpoint,state/'runs')
        with con:
            con.execute('INSERT OR IGNORE INTO endpoints VALUES(?,?,?,?,?)',
              (asset,endpoint['session_date'],core.canonical(endpoint),core.digest(endpoint),fingerprint(root)))
    save(folder/'capture.json',dict(health=health,endpoints=endpoints))
    print('Friday capture:',json.dumps({k:dict(date=v['session_date'],channels=v['channels']) for k,v in endpoints.items()}),flush=True)
    print('Spot source health:',json.dumps(health),flush=True)
    print('Private audit:',folder/'capture.json',flush=True)
    return 0 if len(endpoints)==2 else 1


def slot(now):
    local=now.astimezone(core.TEHRAN)
    return local.replace(hour=18,minute=0,second=0,microsecond=0)


def next_slot(now):
    local=now.astimezone(core.TEHRAN);candidate=slot(now)+timedelta(days=(6-local.weekday())%7)
    return candidate if candidate>local else candidate+timedelta(days=7)


def activated(root,state,assets):
    path=state/'activation.json'
    if path.is_symlink() or not path.is_file(): raise core.RiskError('Risk publisher is not activated.')
    config=json.loads(path.read_text(encoding='utf-8'))
    if (config.get('runtime_hash')!=fingerprint(root) or config.get('assets_hash')!=fingerprint(assets,ASSETS) or
            config.get('schedule')!='Sunday 18:00 Asia/Tehran' or config.get('version')!=core.VERSION):
        raise core.RiskError('Installed risk runtime, assets or schedule differs.')
    return config


def duplicate(con,key):
    row=con.execute('SELECT status,media_id FROM instagram_news_publications WHERE week_key=?',(key,)).fetchone()
    if row and row['status']=='published':
        print('Risk carousel already published:',row['media_id']);return True
    if row and row['status'] in {'preparing','publishing','needs_review'}:
        raise core.RiskError('Earlier publication requires review; no blind duplicate.')
    return False


def verify(comparison,report,state,manifest):
    now=datetime.now(core.TEHRAN)
    if now.weekday()!=6 or not 0<=(now-slot(now)).total_seconds()<1200:
        raise core.RiskError('Risk Feed is allowed only Sunday 18:00–18:20 Tehran.')
    if not 0<=(datetime.now(core.UTC)-core.stamp(report['created_at'])).total_seconds()<600:
        raise core.RiskError('Source-read audit is no longer current.')
    expected=core.compare(report['endpoints'],core.report_friday().isoformat())
    if core.canonical(expected)!=core.canonical(comparison) or comparison.get('layout_sample') or comparison.get('all_verified') is not True:
        raise core.RiskError('Risk comparison differs from its complete verified evidence.')
    for row in comparison['rows']:
        for endpoint in (row['previous'],row['current']): sources.verify_evidence(endpoint,state/'runs')
    if (manifest.get('kind')!='risk_thermometer' or manifest.get('publication_mode')!='scheduled' or
            manifest.get('comparison_hash')!=core.digest(expected) or manifest.get('caption')!=renderer.caption(expected)):
        raise core.RiskError('Manifest or caption differs from verified data.')
    paths,urls=manifest.get('images',[]),manifest.get('image_urls',[])
    if len(paths)!=6 or len(urls)!=6 or len(set(paths))!=6:
        raise core.RiskError('Exactly six unique risk slides are required.')
    for raw,url in zip(paths,urls):
        path=Path(raw)
        if (path.is_symlink() or not path.resolve().is_relative_to(PUBLIC/'risk-thermometer') or
                path.suffix!='.jpg' or url!=BASE+'/risk-thermometer/'+path.name or
                hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['image_sha256'].get(path.name)):
            raise core.RiskError('Risk image location or content changed.')


def publish(con,comparison,report,manifest,assets,state,root):
    activated(root,state,assets);verify(comparison,report,state,manifest)
    key=comparison['week_end']
    if duplicate(con,key): return
    if not os.getenv('INSTAGRAM_ACCESS_TOKEN') or not re.fullmatch('[0-9]+',os.getenv('INSTAGRAM_USER_ID','')):
        raise core.RiskError('Existing private Instagram credentials are not loaded.')
    import instagram_news_batch as batch
    batch.guard()  # Existing core-post and pending-Story reservations, account and usage checks.
    spec=importlib.util.spec_from_file_location('risk_graph_helper',assets/'instagram_daily_rates.py')
    graph=importlib.util.module_from_spec(spec);sys.modules[spec.name]=graph;spec.loader.exec_module(graph)
    for url in manifest['image_urls']: graph.verify_public_image(url)
    with con:
        con.execute('''INSERT INTO instagram_news_publications(week_key,status,started_at,manifest_json)
          VALUES (?,'preparing',?,?) ON CONFLICT(week_key) DO UPDATE SET status='preparing',started_at=excluded.started_at,
          finished_at=NULL,container_id=NULL,media_id=NULL,manifest_json=excluded.manifest_json,error_type=NULL''',
          (key,time.time(),core.canonical(manifest)))
    final_started=False
    try:
        children=[]
        for url in manifest['image_urls']:
            child=graph._create_container(dict(image_url=url,is_carousel_item='true'))
            if not re.fullmatch('[0-9]+',str(child)): raise core.RiskError('Invalid Meta child ID.')
            graph._wait_for_container(child);children.append(str(child))
        parent=graph._create_container(dict(media_type='CAROUSEL',children=','.join(children),caption=manifest['caption']))
        if not re.fullmatch('[0-9]+',str(parent)): raise core.RiskError('Invalid Meta carousel ID.')
        with con: con.execute('UPDATE instagram_news_publications SET container_id=? WHERE week_key=?',(str(parent),key))
        graph._wait_for_container(parent)
        activated(root,state,assets);verify(comparison,report,state,manifest);batch.guard()
        with con: con.execute("UPDATE instagram_news_publications SET status='publishing' WHERE week_key=?",(key,))
        final_started=True
        media=graph._publish_container(parent)
        if not re.fullmatch('[0-9]+',str(media)): raise core.RiskError('Invalid Meta published ID.')
        with con:
            con.execute("UPDATE instagram_news_publications SET status='published',finished_at=?,media_id=? WHERE week_key=?",(time.time(),str(media),key))
        print('Published weekly risk carousel:',media,flush=True)
    except BaseException as exc:
        with con:
            con.execute('UPDATE instagram_news_publications SET status=?,finished_at=?,error_type=? WHERE week_key=?',
              ('needs_review' if final_started else 'failed',time.time(),type(exc).__name__,key))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    for action in ('probe','capture','scheduled','preview','layout-preview','status'): group.add_argument('--'+action,action='store_true')
    parser.add_argument('--state',type=Path,default=STATE)
    parser.add_argument('--asset-root',type=Path,default=Path.home()/'kiani-instagram-publisher')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();os.umask(0o077);root=Path(__file__).resolve().parent
    if args.scheduled or args.capture:
        if args.state.resolve()!=STATE.resolve() or args.output or args.asset_root.resolve()!=(Path.home()/'kiani-instagram-publisher').resolve():
            raise core.RiskError('Scheduled workers use only the installed state, assets and public media directory.')
        activated(root,args.state,args.asset_root)
        now=datetime.now(core.UTC)
        if args.capture and core.capture_anchor(now) is None: return 0
        if args.scheduled and (now.astimezone(core.TEHRAN).weekday()!=6 or not 0<=(now.astimezone(core.TEHRAN)-slot(now)).total_seconds()<900): return 0
    if args.layout_preview:
        images=renderer.render(core.sample(),args.output or PUBLIC/'risk-thermometer-preview',args.asset_root,preview=True)
        for p in images:
            print('Fictional risk layout:',BASE+'/risk-thermometer-preview/'+Path(p).name if not args.output else p,flush=True)
        if args.state.resolve()==STATE.resolve() and not args.output and args.asset_root.resolve()==(Path.home()/'kiani-instagram-publisher').resolve():
            args.state.mkdir(parents=True,exist_ok=True,mode=0o700)
            proof=args.state/'layout-proof.json'
            if proof.is_symlink(): raise core.RiskError('Refusing symlink layout proof.')
            proof.write_text(core.canonical(dict(runtime_hash=fingerprint(root),assets_hash=fingerprint(args.asset_root,ASSETS),
                created_at=time.time(),images={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images})),encoding='utf-8')
            proof.chmod(0o600)
        print('Fictional design only; no source history or Instagram contact.');return 0
    with locked(args.state/'publisher.lock'):
        con=database(args.state/'risk.sqlite3')
        try:
            if args.status:
                print('Next risk slot:',next_slot(datetime.now(core.UTC)).isoformat())
                print('Frozen spot endpoints:',dict(con.execute('SELECT asset,count(*) FROM endpoints GROUP BY asset')))
                print('Publication states:',dict(con.execute('SELECT status,count(*) FROM instagram_news_publications GROUP BY status')))
                return 0
            folder=run_folder(args.state)
            if args.capture: return capture(con,args.state,folder,root)
            if args.scheduled and duplicate(con,core.report_friday().isoformat()): return 0
            report=collect(con,args.state,folder)
            print('Public source health:',json.dumps(report['health']),flush=True)
            if not args.scheduled and not args.preview:
                _,spot_health=sources.capture_spots(folder,probe=True)
                report['spot_probe']=spot_health
                public_ready=all(bool(rows) and (core.day(max(rows))-timedelta(days=7)).isoformat() in rows
                    and 0<=(core.report_friday()-core.day(max(rows))).days<=core.MAX_LAG[a]
                    for a,rows in ((a,report['endpoints'].get(a,{})) for a in core.ASSETS if a not in core.SPOT))
                spot_ready=all(spot_health.get(a+'_agreement',{}).get('status')=='ok' for a in core.SPOT)
                report['preflight_passed']=public_ready and spot_ready
                save(folder/'preflight.json',report)
                if report['preflight_passed']:
                    with con: con.execute('INSERT INTO preflights VALUES(?,?,?,?,?)',(folder.name,time.time(),fingerprint(root),fingerprint(args.asset_root,ASSETS),core.canonical(report)))
                print('Current spot health:',json.dumps(spot_health),flush=True)
                print('Preflight:', 'passed' if report['preflight_passed'] else 'blocked',flush=True)
                print('Private audit:',folder/'preflight.json',flush=True)
                print('No Instagram contact. Current probes never enter weekly spot history.')
                return 0 if report['preflight_passed'] else 1
            comparison=report['comparison']
            if not comparison:
                print('HELD risk post:',report['hold_reason'],'No post published.',flush=True)
                print('Private audit:',folder/'source.json',flush=True);return 0 if args.scheduled else 1
            images=renderer.render(comparison,args.output or PUBLIC/('risk-thermometer-preview' if args.preview else 'risk-thermometer'),args.asset_root,preview=args.preview)
            manifest=dict(kind='risk_thermometer',publication_mode='preview' if args.preview else 'scheduled',images=images,
                image_urls=[BASE+'/risk-thermometer/'+Path(p).name for p in images],caption=renderer.caption(comparison),
                comparison_hash=core.digest(comparison),image_sha256={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images})
            save(folder/'manifest.json',manifest)
            if args.preview:
                for p in images: print('Risk preview:',p)
                print('No Instagram contact.');return 0
            publish(con,comparison,report,manifest,args.asset_root,args.state,root)
            return 0
        finally: con.close()


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Risk worker stopped:',str(exc) if isinstance(exc,core.RiskError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
