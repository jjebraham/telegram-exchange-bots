#!/usr/bin/env python3
"""Install one weekly Feed, daily observations, and compatible Story/insights adapters."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from datetime import datetime, timedelta
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

STORY_OLD={'instagram_delayed_stories.py':'d03895940f804f59e74b705abf5dfd68c51f15c3bb651b0147ebfd97a0bd98db',
           'instagram_story_renderer.py':'212ee1ffd453b56152d1117cb6f74972eb80fbf8ddb0d85249c67470b62a5de0'}
ANALYTICS_OLD={'instagram_insights_data.py':'89fac1394ec3987e9f6d3ab72aee63efc1cd034e9e7d04431604d9d1ffc12368',
               'instagram_post_insights.py':'58cca39bf07151927de58a0fa128bf218d721f4f10f0d910e89beb61ce2a826f',
               'instagram_news_retention.py':'b5dab891f550061f8dbce1cbe49db2c75ffe6cc6b7230080de25bc9c1c450e40'}
BEGIN,END='# BEGIN Kiani weekly market comparison','# END Kiani weekly market comparison'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def owned(path,private=False):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid():
        raise RuntimeError('Expected an existing publisher-owned regular file: '+str(path))
    if private and path.stat().st_mode&0o077:
        raise RuntimeError('Private file permissions need review: '+str(path))
    return path.read_bytes()


def atomic(path,raw,mode=0o600):
    if path.is_symlink(): raise RuntimeError('Refusing a symlink install target.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temp,mode); os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def cron(): return subprocess.check_output(['crontab','-l'],timeout=15)


def release(source,target,names):
    for name in names:
        raw=(source/name).read_bytes(); path=target/name
        if path.is_symlink() or path.exists() and path.read_bytes()!=raw:
            raise RuntimeError('An existing versioned release differs: '+name)
        if not path.exists(): atomic(path,raw)


def hourly_wrappers(home, runtime):
    python = shlex.quote(str(home / 'kiani-instagram-venv/bin/python'))
    script = shlex.quote(str(runtime / 'instagram_ranked_news.py'))
    header = '''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 077
action="${1:-publish}"
case "$action" in
'''
    outputs = {}
    for kind, filename in (('crypto', 'publish-kiani-instagram-news.sh'), ('economy', 'publish-kiani-instagram-economy.sh')):
        text = header
        if kind == 'economy':
            text += f'  collect) exec {python} -u {script} --kind economy --collect-only ;;\n'
        text += '''  publish) slot="hour-$(date +%H)" ;;
  *) echo "Usage: publish''' + ('|collect' if kind == 'economy' else '') + '''" >&2; exit 2 ;;
esac
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''
        text += f'exec {python} -u {script} --kind {kind} --slot "$slot" --publish\n'
        outputs[home / filename] = text.encode()
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True); parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    if not hasattr(os,'geteuid') or os.geteuid()==0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        parser.error('Use the pinned revision as the existing publisher user without sudo.')
    os.umask(0o077); home=Path.home(); source=args.runtime.resolve(); sys.path.insert(0,str(source))
    import instagram_weekly_markets as app
    import weekly_market_data as prices
    assets=home/'kiani-instagram-publisher'
    app.labels(datetime.now(app.TEHRAN),assets)
    if datetime.now(app.TEHRAN).utcoffset()!=timedelta(hours=3,minutes=30):
        raise RuntimeError('Tehran timezone rules changed; review the UTC cron conversion.')
    zone=subprocess.check_output(['timedatectl','show','--property=Timezone','--value'],text=True,timeout=15).strip()
    if zone not in {'UTC','Etc/UTC'} or subprocess.run(['systemctl','is-active','--quiet','cron'],timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    python=home/'kiani-instagram-venv/bin/python'
    if not python.is_file() or not os.access(python,os.X_OK): raise RuntimeError('Existing publisher Python is unavailable.')
    for path in source.rglob('*.py'): ast.parse(path.read_text(encoding='utf-8'),filename=str(path),feature_version=(3,11))
    # Existing credentials are checked locally only, never printed or rotated.
    owned(home/'.kiani-instagram.env',private=True)
    con=app.database(app.STATE/'markets.sqlite3')
    try:
        preview=con.execute('''SELECT * FROM preflights WHERE runtime_hash=? AND assets_hash=?
            AND created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 1''',
            (app.fingerprint(source),app.fingerprint(assets,app.ASSETS),time.time()-180,time.time())).fetchone()
        if not preview: raise RuntimeError('A fresh, successful source preflight from this exact runtime is required.')
        prices.validate(json.loads(preview['snapshot_json']),live=True)
    finally: con.close()
    story_config=home/'.local/state/kiani-instagram-stories/config.json'
    original_config=owned(story_config,private=True); config=json.loads(original_config)
    if not {'rates','economy','top50','crypto','iran_gold'}<=set(config.get('sources',{})):
        raise RuntimeError('Existing Story sources differ from the confirmed setup.')
    if config.get('public_root')!=str(app.PUBLIC) or config.get('public_base','').rstrip('/')!=app.BASE:
        raise RuntimeError('Existing public image configuration differs.')
    dbpath=str(app.STATE/'markets.sqlite3')
    if config['sources'].get('weekly_markets',dbpath)!=dbpath: raise RuntimeError('A different weekly comparison is configured.')
    config['sources']['weekly_markets']=dbpath
    story_db=Path(config['db'])
    with sqlite3.connect(story_db.resolve().as_uri()+'?mode=ro',uri=True) as check:
        if not check.execute("SELECT 1 FROM settings WHERE key='activated_at'").fetchone(): raise RuntimeError('Story worker is not activated.')
    metadata_path=home/'.local/state/kiani-instagram-insights/activation.json'
    original_meta=owned(metadata_path,private=True); prior=json.loads(original_meta)
    old_revision=prior.get('revision','')
    if not re.fullmatch('[0-9a-f]{40}',old_revision): raise RuntimeError('Invalid installed analytics revision.')
    old_root=home/'kiani-instagram-insights-releases'/old_revision
    analytics_launcher=home/'collect-kiani-instagram-insights.sh'
    original_analytics_launcher=owned(analytics_launcher)
    old_script=str(old_root/'instagram_post_insights.py').encode()
    if original_analytics_launcher.count(old_script)!=1: raise RuntimeError('Analytics launcher differs from its installed revision.')
    if prior.get('policy',{}).get('keep_at_or_above_views')!=200 or prior.get('policy',{}).get('assessment_hours')!=2:
        raise RuntimeError('Expected the confirmed two-hour/200-view news policy.')
    # Clone the analytics release. Only the category registry changes; the exact
    # installed collector/deletion modules, permissions, policy and DB stay intact.
    for name,expected in ANALYTICS_OLD.items():
        raw=owned(old_root/name)
        target=(source/name).read_bytes()
        if sha(raw)!=expected and raw!=target: raise RuntimeError('Installed analytics differs from the reviewed file: '+name)
        if name!='instagram_insights_data.py' and raw!=target:
            raise RuntimeError('The weekly installer may not change analytics or deletion logic.')
    new_analytics=home/'kiani-instagram-insights-releases'/args.revision
    release(source,new_analytics,tuple(ANALYTICS_OLD))
    runtime_hash=sha(b'\0'.join(n.encode()+b'\0'+(new_analytics/n).read_bytes() for n in ANALYTICS_OLD))
    old_hash=sha(b'\0'.join(n.encode()+b'\0'+(old_root/n).read_bytes() for n in ANALYTICS_OLD))
    if prior.get('runtime_hash')!=old_hash: raise RuntimeError('Installed analytics fingerprint differs.')
    # Hourly news also imports the read-only inventory module to reserve Story
    # quota. Extend its registry too, so the new protected kind cannot halt news.
    news_revision=prior.get('news_runtime_revision',old_revision)
    if not re.fullmatch('[0-9a-f]{40}',news_revision): raise RuntimeError('Invalid installed news revision.')
    news_pin=prior.get('previous_news_runtime_revision',news_revision) if prior.get('category_extension')=='weekly_markets' and news_revision==args.revision else news_revision
    if not re.fullmatch('[0-9a-f]{40}',news_pin): raise RuntimeError('Invalid original news pin.')
    news_root=home/'kiani-instagram-ranked-news-releases'/news_revision
    news_new=home/'kiani-instagram-ranked-news-releases'/args.revision
    news_names=('instagram_ranked_news.py','crypto_news_trial.py','instagram_news_batch.py','instagram_insights_data.py',
        'selector_trial_runtime/economy_news_picker.py','selector_trial_runtime/economy_news_translation.py',
        'selector_trial_runtime/instagram_crypto_news.py','selector_trial_runtime/instagram_news_renderer.py','selector_trial_runtime/PINNED.md')
    news_before={}; news_hashes={}
    for name in news_names:
        raw=owned(news_root/name)
        pinned=subprocess.check_output(['git','-C',str(home/'telegram_bot_repo'),'show',news_pin+':'+name],timeout=20)
        if raw!=pinned and not (name=='instagram_insights_data.py' and raw==(source/name).read_bytes()):
            raise RuntimeError('Installed hourly news differs from its pinned source: '+name)
        news_before[news_root/name]=raw; news_hashes[name]=sha(raw)
        target=(source/name).read_bytes() if name=='instagram_insights_data.py' else raw
        path=news_new/name
        if path.is_symlink() or path.exists() and path.read_bytes()!=target: raise RuntimeError('An existing news release differs.')
        if not path.exists(): atomic(path,target)
    new_meta=dict(prior,revision=args.revision,runtime_hash=runtime_hash,category_extension='weekly_markets',
                  previous_insights_revision=old_revision,news_runtime_revision=args.revision,
                  previous_news_runtime_revision=news_pin,news_source_hashes=news_hashes)
    release_root=home/'kiani-instagram-weekly-markets-releases'/args.revision
    release(source,release_root,app.FILES)
    launcher=home/'publish-kiani-instagram-weekly-markets.sh'
    wrapper=('''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONIOENCODING=utf-8
export TZ=Asia/Tehran
umask 077
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''+ 'exec '+shlex.quote(str(python))+' -u '+shlex.quote(str(release_root/'instagram_weekly_markets.py'))+' --scheduled\n').encode()
    changed={launcher:(wrapper,0o700),story_config:(json.dumps(config,indent=2).encode()+b'\n',0o600),
             analytics_launcher:(original_analytics_launcher.replace(old_script,str(new_analytics/'instagram_post_insights.py').encode()),0o700),
             metadata_path:(json.dumps(new_meta,indent=2).encode(),0o600)}
    old_news_wrappers=hourly_wrappers(home,news_root)
    new_news_wrappers=hourly_wrappers(home,news_new)
    for path,expected in old_news_wrappers.items():
        if owned(path)!=expected:
            raise RuntimeError('An hourly news launcher differs from its reviewed layout: '+path.name)
        # Economy intentionally has TWO references: collect-only and publish.
        # Reproduce the deployed wrapper verbatim, changing only its runtime path.
        changed[path]=(new_news_wrappers[path],path.stat().st_mode&0o777)
    print('Existing hourly launchers verified: crypto publish; economy collect and publish.',flush=True)
    story_root=home/'kiani-instagram-story-publisher'
    for name,expected in STORY_OLD.items():
        path=story_root/name; raw=owned(path); target=(source/name).read_bytes()
        if sha(raw)!=expected and raw!=target: raise RuntimeError('Installed Story worker differs: '+name)
        changed[path]=(target,path.stat().st_mode&0o777)
    before={p:(owned(p),p.stat().st_mode&0o777) if p.exists() else None for p in changed}
    activation_path=app.STATE/'activation.json'
    activation_old=owned(activation_path) if activation_path.exists() else None
    if launcher.exists() and not activation_old: raise RuntimeError('Unregistered weekly launcher already exists.')
    old_weekly=json.loads(activation_old) if activation_old else {}
    if launcher.exists() and old_weekly.get('revision')!=args.revision:
        raise RuntimeError('A different weekly release is active; review it before upgrading.')
    initial_cron=cron(); command=f'30,35,40 16 * * * {launcher} >> {home}/kiani-instagram-weekly-markets-cron.log 2>&1'
    kept=[]
    for line in initial_cron.decode().splitlines():
        stripped=line.strip()
        if stripped.startswith('CRON_TZ=') and stripped.split('=',1)[1].strip('"\'') not in {'UTC','Etc/UTC'}:
            raise RuntimeError('Non-UTC crontab timezone needs review.')
        if stripped in {BEGIN,END}: continue
        if str(launcher) in line and not stripped.startswith('#'):
            if stripped!=command: raise RuntimeError('An existing weekly market cron entry differs.')
            continue
        kept.append(line)
    replacement=('\n'.join(kept).rstrip()+'\n\n'+BEGIN+'\n'+command+'\n'+END+'\n').encode()
    # Hold all affected workers so no half-installed adapter can read a new kind.
    with ExitStack() as stack:
        for path in sorted([app.STATE/'publication.lock',story_db.with_suffix('.lock'),metadata_path.parent/'collector.lock',
                            home/'.local/state/kiani-instagram-news-ranking/selection.lock',
                            home/'.local/state/kiani-instagram-news-ranking/economy.collection.lock',
                            home/'.local/state/kiani-instagram-news-ranking/crypto.collection.lock']):
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if path.is_symlink(): raise RuntimeError('Refusing symlink lock.')
            handle=stack.enter_context(path.open('a')); path.chmod(0o600)
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('A publisher or analytics worker is active; retry installation after it finishes.') from None
        if (cron()!=initial_cron or any(p.exists()!=bool(old) or old and owned(p)!=old[0] for p,old in before.items())
                or any(owned(p)!=raw for p,raw in news_before.items())):
            raise RuntimeError('Publisher configuration changed during preparation.')
        backup=Path(tempfile.mkdtemp(prefix='kiani-instagram-weekly-markets-backup-',dir=home))
        atomic(backup/'crontab.txt',initial_cron)
        atomic(backup/'paths.json',json.dumps([str(p) for p in changed]).encode())
        for i,old in enumerate(before.values()):
            if old: atomic(backup/str(i),old[0],old[1])
        if activation_old: atomic(backup/'activation.json',activation_old)
        saved=json.dumps(dict(revision=args.revision,activated_at=time.time(),backup=str(backup),
            preflight=preview['id'],runtime_hash=app.fingerprint(source),schedule='Thursday 20:00 Asia/Tehran',
            daily_observation='20:00 Asia/Tehran',source_policy=prices.VERSION)).encode()
        cron_installed=False
        try:
            for p,(raw,mode) in changed.items(): atomic(p,raw,mode)
            if cron()!=initial_cron: raise RuntimeError('Crontab changed during installation.')
            subprocess.run(['crontab','-'],input=replacement,capture_output=True,check=True,timeout=15); cron_installed=True
            if cron()!=replacement: raise RuntimeError('Installed schedule does not match.')
            atomic(activation_path,saved)
        except BaseException:
            if cron()==replacement:
                subprocess.run(['crontab','-'],input=initial_cron,capture_output=True,check=True,timeout=15)
            for p,old in reversed(list(before.items())):
                if p.exists() and owned(p)==changed[p][0]:
                    if old: atomic(p,*old)
                    else: p.unlink()
            if activation_path.exists() and owned(activation_path)==saved:
                if activation_old: atomic(activation_path,activation_old)
                else: activation_path.unlink()
            print('Installation incomplete. Backup:',backup,file=sys.stderr); raise
    slot=app.next_thursday(datetime.now(app.TEHRAN))
    con=app.database(app.STATE/'markets.sqlite3')
    try: baseline=app.observation(con,slot.astimezone(prices.UTC)-timedelta(days=7))
    finally: con.close()
    print('Backup:',backup)
    print('Installed weekly market comparison:',args.revision)
    print('Daily verified observation: 20:00 Asia/Tehran (16:30 UTC); bounded retries 20:05 and 20:10.')
    print('Weekly Feed: Thursday 20:00 Asia/Tehran, at most one success/week. Story follows success +30min.')
    print('Next Thursday observation:',slot.isoformat())
    print('Earliest full comparison:',(slot if baseline else slot+timedelta(days=7)).isoformat())
    print('A matching seven-day baseline and all five verified markets are mandatory; missing/stale data skips the post.')
    print('Existing prices/news schedules, credentials, retention policy, enrollment, decisions and queued Stories preserved.')
    print('Activation complete. No Instagram post was published or deleted during installation.')
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Weekly activation stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
