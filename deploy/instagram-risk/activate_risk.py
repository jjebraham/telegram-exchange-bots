#!/usr/bin/env python3
"""Install a guarded Sunday risk carousel without changing existing posting policy."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from datetime import datetime,timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time

BASE_ANALYTICS='4745d848a1253b5c3ec39bf86a723b4c560ff8cd'
BASE_NEWS='8f232939e8609b9855272582bf3222331afff3b5'
ANALYTICS=('instagram_insights_data.py','instagram_post_insights.py','instagram_news_retention.py')
NEWS=('instagram_ranked_news.py','crypto_news_trial.py','instagram_news_batch.py','instagram_insights_data.py',
      'selector_trial_runtime/economy_news_picker.py','selector_trial_runtime/economy_news_translation.py',
      'selector_trial_runtime/instagram_crypto_news.py','selector_trial_runtime/instagram_news_renderer.py','selector_trial_runtime/PINNED.md')
BEGIN,END='# BEGIN Kiani weekly risk dashboard','# END Kiani weekly risk dashboard'


def owned(path,private=False):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid():
        raise RuntimeError('Expected a publisher-owned regular file: '+str(path))
    if private and path.stat().st_mode&0o077: raise RuntimeError('Private file permissions need review: '+str(path))
    return path.read_bytes()


def atomic(path,raw,mode=0o600):
    if path.is_symlink(): raise RuntimeError('Refusing a symlink install target.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(raw);out.flush();os.fsync(out.fileno())
        os.chmod(temp,mode);os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def cron(): return subprocess.check_output(['crontab','-l'],timeout=15)
def fingerprint(root,names): return sha(b'\0'.join(n.encode()+b'\0'+owned(root/n) for n in names))


def install_file(path,raw):
    if path.exists():
        if owned(path)!=raw: raise RuntimeError('Immutable release differs: '+str(path))
    else: atomic(path,raw)


def hourly_wrappers(home,runtime):
    python=shlex.quote(str(home/'kiani-instagram-venv/bin/python'))
    script=shlex.quote(str(runtime/'instagram_ranked_news.py'))
    header='''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 077
action="${1:-publish}"
case "$action" in
'''
    outputs={}
    for kind,name in (('crypto','publish-kiani-instagram-news.sh'),('economy','publish-kiani-instagram-economy.sh')):
        text=header
        if kind=='economy': text+=f'  collect) exec {python} -u {script} --kind economy --collect-only ;;\n'
        text+='''  publish) slot="hour-$(date +%H)" ;;
  *) echo "Usage: publish'''+('|collect' if kind=='economy' else '')+'''" >&2; exit 2 ;;
esac
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''
        outputs[home/name]=(text+f'exec {python} -u {script} --kind {kind} --slot "$slot" --publish\n').encode()
    return outputs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',required=True,type=Path);p.add_argument('--revision',required=True)
    args=p.parse_args()
    if not hasattr(os,'geteuid') or os.geteuid()==0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        p.error('Use a pinned revision as the existing publisher user without sudo.')
    os.umask(0o077);home=Path.home();source=args.runtime.resolve();sys.path.insert(0,str(source))
    import instagram_risk_thermometer as app
    import risk_market_core as core
    assets=home/'kiani-instagram-publisher'
    for path in source.rglob('*.py'): ast.parse(path.read_text(encoding='utf-8'),filename=str(path),feature_version=(3,11))
    app.renderer.labels(datetime.now(core.TEHRAN),assets)
    layout=json.loads(owned(app.STATE/'layout-proof.json',True))
    if (layout.get('runtime_hash')!=app.fingerprint(source) or layout.get('assets_hash')!=app.fingerprint(assets,app.ASSETS) or
            not 0<=time.time()-layout.get('created_at',0)<7*86400 or len(layout.get('images',{}))!=6):
        raise RuntimeError('Render the six-slide layout preview from this exact revision first.')
    for raw,expected in layout['images'].items():
        path=Path(raw)
        if not path.resolve().is_relative_to(app.PUBLIC/'risk-thermometer-preview') or sha(owned(path))!=expected:
            raise RuntimeError('Saved layout proof differs.')
    if datetime.now(core.TEHRAN).utcoffset()!=timedelta(hours=3,minutes=30): raise RuntimeError('Tehran timezone rules require review.')
    zone=subprocess.check_output(['timedatectl','show','--property=Timezone','--value'],text=True,timeout=15).strip()
    if zone not in {'UTC','Etc/UTC'} or subprocess.run(['systemctl','is-active','--quiet','cron'],timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    owned(home/'.kiani-instagram.env',private=True)
    python=home/'kiani-instagram-venv/bin/python'
    if not python.is_file() or not os.access(python,os.X_OK): raise RuntimeError('Existing publisher Python is unavailable.')
    con=app.database(app.STATE/'risk.sqlite3')
    try:
        proof=con.execute('''SELECT * FROM preflights WHERE created_at BETWEEN ? AND ? AND runtime_hash=? AND assets_hash=?
            ORDER BY created_at DESC LIMIT 1''',(time.time()-600,time.time(),app.fingerprint(source),app.fingerprint(assets,app.ASSETS))).fetchone()
        if not proof or json.loads(proof['report_json']).get('preflight_passed') is not True:
            raise RuntimeError('A fresh complete source preflight from this exact runtime and assets is required.')
    finally: con.close()
    meta_path=home/'.local/state/kiani-instagram-insights/activation.json';old_meta=owned(meta_path,True);meta=json.loads(old_meta)
    if meta.get('revision')!=BASE_ANALYTICS or meta.get('news_runtime_revision')!=BASE_NEWS:
        raise RuntimeError('Installed analytics/news differs from the confirmed PR75/PR77 versions; nothing replaced.')
    if (meta.get('hourly_news_enabled') is not True or meta.get('news_schedule',{}).get('per_slot')!=1 or
        meta.get('news_schedule',{}).get('per_category_day')!=10 or meta.get('policy',{}).get('assessment_hours')!=2 or
        meta.get('policy',{}).get('keep_at_or_above_views')!=200 or meta.get('news_template',{}).get('body_font_px')!=64):
        raise RuntimeError('Existing news schedule, retention or readable layout differs.')
    analytics_old=home/'kiani-instagram-insights-releases'/BASE_ANALYTICS
    analytics_new=home/'kiani-instagram-insights-releases'/args.revision
    protected={};news_hashes={}
    for name in ANALYTICS:
        raw=owned(analytics_old/name);target=owned(source/name)
        expected=target.replace(b", 'risk_thermometer'",b'') if name=='instagram_insights_data.py' else target
        if raw!=expected: raise RuntimeError('Existing analytics/deletion differs: '+name)
        protected[analytics_old/name]=raw;install_file(analytics_new/name,target)
    if fingerprint(analytics_old,ANALYTICS)!=meta.get('runtime_hash'): raise RuntimeError('Analytics fingerprint differs.')
    news_old=home/'kiani-instagram-ranked-news-releases'/BASE_NEWS;news_new=home/'kiani-instagram-ranked-news-releases'/args.revision
    for name in NEWS:
        raw=owned(news_old/name)
        pinned=subprocess.check_output(['git','-C',str(home/'telegram_bot_repo'),'show',BASE_NEWS+':'+name],timeout=20)
        if raw!=pinned or sha(raw)!=meta.get('news_source_hashes',{}).get(name):
            raise RuntimeError('Installed readable news differs from its verified source: '+name)
        protected[news_old/name]=raw
        target=owned(source/name) if name=='instagram_insights_data.py' else raw
        install_file(news_new/name,target);news_hashes[name]=sha(target)
    new_meta=dict(meta,revision=args.revision,runtime_hash=fingerprint(analytics_new,ANALYTICS),
        previous_insights_revision=BASE_ANALYTICS,news_runtime_revision=args.revision,previous_news_runtime_revision=BASE_NEWS,
        news_source_hashes=news_hashes,category_extension='risk_thermometer')
    new_meta['news_template']=dict(meta['news_template'],runtime_hash=fingerprint(news_new,NEWS[:-1]),registry_extension_revision=args.revision)
    config_path=home/'.local/state/kiani-instagram-stories/config.json';old_config=owned(config_path,True);config=json.loads(old_config)
    if config.get('public_root')!=str(app.PUBLIC) or config.get('public_base','').rstrip('/')!=app.BASE or 'weekly_markets' not in config.get('sources',{}):
        raise RuntimeError('Story sources/public configuration differs from the confirmed setup.')
    dbpath=str(app.STATE/'risk.sqlite3')
    if 'risk_thermometer' in config['sources']: raise RuntimeError('Risk series is already registered; use its status command.')
    config['sources']['risk_thermometer']=dbpath;story_db=Path(config['db'])
    with sqlite3.connect(story_db.resolve().as_uri()+'?mode=ro',uri=True) as check:
        if not check.execute("SELECT 1 FROM settings WHERE key='activated_at'").fetchone(): raise RuntimeError('Story worker is not activated.')
    release=home/'kiani-instagram-risk-releases'/args.revision
    for name in app.FILES: install_file(release/name,owned(source/name))
    launcher=home/'publish-kiani-instagram-risk.sh'
    if launcher.exists() or (app.STATE/'activation.json').exists(): raise RuntimeError('Risk worker already installed; inspect its status.')
    wrapper=('''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONIOENCODING=utf-8
export TZ=Asia/Tehran
umask 077
case "${1:-scheduled}" in
  capture) action=--capture ;;
  scheduled) action=--scheduled ;;
  status) action=--status ;;
  *) exit 2 ;;
esac
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''+f'exec {shlex.quote(str(python))} -u {shlex.quote(str(release/"instagram_risk_thermometer.py"))} "$action"\n').encode()
    analytics_launcher=home/'collect-kiani-instagram-insights.sh';old_launcher=owned(analytics_launcher)
    old_script=str(analytics_old/'instagram_post_insights.py').encode()
    if old_launcher.count(old_script)!=1: raise RuntimeError('Analytics launcher differs.')
    changed={launcher:(wrapper,0o700),meta_path:(json.dumps(new_meta,indent=2).encode(),0o600),
        config_path:(json.dumps(config,indent=2).encode(),0o600),
        analytics_launcher:(old_launcher.replace(old_script,str(analytics_new/'instagram_post_insights.py').encode()),0o700)}
    new_wrappers=hourly_wrappers(home,news_new)
    for path,expected in hourly_wrappers(home,news_old).items():
        if owned(path)!=expected: raise RuntimeError('Hourly launcher differs: '+path.name)
        changed[path]=(new_wrappers[path],path.stat().st_mode&0o777)
    for name in ('instagram_delayed_stories.py','instagram_story_renderer.py'):
        path=home/'kiani-instagram-story-publisher'/name;raw=owned(path);target=owned(source/name)
        if raw!=target.replace(b", 'risk_thermometer'",b''): raise RuntimeError('Existing Story worker differs: '+name)
        changed[path]=(target,path.stat().st_mode&0o777)
    before={p:(owned(p),p.stat().st_mode&0o777) if p.exists() else None for p in changed}
    initial=cron();lines=initial.decode().splitlines()
    if any(l.strip().startswith('CRON_TZ=') and l.split('=',1)[1].strip(' \"\'') not in {'UTC','Etc/UTC'} for l in lines):
        raise RuntimeError('Non-UTC crontab timezone needs review.')
    if any(str(launcher) in l or l.strip() in {BEGIN,END} for l in lines): raise RuntimeError('Existing risk schedule needs review.')
    entries=[f'0,5,10 21,22 * * 5 {launcher} capture >> {home}/kiani-instagram-risk-cron.log 2>&1',
             f'30,35,40 14 * * 0 {launcher} scheduled >> {home}/kiani-instagram-risk-cron.log 2>&1']
    replacement=(initial.decode().rstrip()+'\n\n'+BEGIN+'\n'+'\n'.join(entries)+'\n'+END+'\n').encode()
    saved=json.dumps(dict(version=core.VERSION,revision=args.revision,runtime_hash=app.fingerprint(release),
        assets_hash=app.fingerprint(assets,app.ASSETS),activated_at=time.time(),preflight=proof['id'],
        schedule='Sunday 18:00 Asia/Tehran',spot_capture='Friday 17:00 America/New_York',
        public_data_policy='dated observations; documented release lag; seven exact inputs')).encode()
    locks=[app.STATE/'publisher.lock',story_db.with_suffix('.lock'),meta_path.parent/'collector.lock',
        home/'.local/state/kiani-instagram-news-ranking/selection.lock',
        home/'.local/state/kiani-instagram-news-ranking/economy.collection.lock',
        home/'.local/state/kiani-instagram-news-ranking/crypto.collection.lock',
        home/'.local/state/kiani-instagram-news/publisher.lock',home/'.local/state/kiani-instagram-news/news.sqlite3.lock',
        home/'.local/state/kiani-instagram-economy/economy.sqlite3.lock']
    with ExitStack() as stack:
        for path in sorted(locks):
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if path.is_symlink(): raise RuntimeError('Refusing a symlink worker lock.')
            h=stack.enter_context(path.open('a'))
            try: fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('A publisher/analytics worker is active; retry activation after it finishes.') from None
        if (cron()!=initial or fingerprint(assets,app.ASSETS)!=layout['assets_hash'] or
            any(p.exists()!=bool(old) or old and owned(p)!=old[0] for p,old in before.items())
            or any(owned(p)!=raw for p,raw in protected.items())): raise RuntimeError('Installed files changed during preparation.')
        backup=Path(tempfile.mkdtemp(prefix='kiani-instagram-risk-backup-',dir=home))
        atomic(backup/'crontab.txt',initial);atomic(backup/'paths.json',json.dumps([str(p) for p in changed]).encode())
        for i,old in enumerate(before.values()):
            if old: atomic(backup/str(i),old[0],old[1])
        try:
            for path,(raw,mode) in changed.items(): atomic(path,raw,mode)
            if cron()!=initial: raise RuntimeError('Crontab changed during installation.')
            subprocess.run(['crontab','-'],input=replacement,capture_output=True,check=True,timeout=15)
            if cron()!=replacement: raise RuntimeError('Installed schedule differs.')
            atomic(app.STATE/'activation.json',saved)
        except BaseException:
            if cron()==replacement: subprocess.run(['crontab','-'],input=initial,capture_output=True,check=True,timeout=15)
            for path,old in reversed(list(before.items())):
                if path.exists() and owned(path)==changed[path][0]:
                    if old: atomic(path,*old)
                    else: path.unlink()
            activation=app.STATE/'activation.json'
            if activation.exists() and owned(activation)==saved: activation.unlink()
            print('Installation incomplete. Backup:',backup,file=sys.stderr);raise
    print('Backup:',backup)
    print('Installed free-data risk dashboard:',args.revision)
    print('Weekly Feed: Sunday 18:00 Asia/Tehran; bounded retries 18:05 and 18:10; at most one success/week.')
    print('Six-slide carousel; cover Story 30 minutes after successful Feed. Protected from news deletion.')
    print('Friday gold/BTC capture: 17:00 New York; timezone handles daylight saving. No backfill from current quotes.')
    print('Seven dated indicators: gold, Brent SPOT, BTC, VIX, Fed BROAD dollar, 10-year yield, STLFSI4.')
    print('Missing/disagreeing data holds the entire post. Official series have disclosed release lags.')
    print('News layout, hourly slots, 200-Views/two-hour rule, enrollment, decisions and existing schedules preserved.')
    print('Activation complete. No immediate Instagram publishing or deletion.')
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Risk activation stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
