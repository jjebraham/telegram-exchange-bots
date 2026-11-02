#!/usr/bin/env python3
"""Verify and switch the existing hourly news publishers to illustrated slides."""
from contextlib import ExitStack, closing
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

BASE = 'a22cb107c66c366a50127aee49d13cb6bb44f7f2'
OLD_FILES = ('instagram_ranked_news.py','crypto_news_trial.py','instagram_news_batch.py','instagram_insights_data.py',
    'selector_trial_runtime/economy_news_picker.py','selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py','selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md')
EXTRA = ('instagram_news_slide_images.py','instagram_reel_source_image.py',
         'instagram_reel_stock.py','instagram_reel_commons.py')
ASSETS = ('assets/instagram/kiani-logo.svg','fonts/Vazirmatn-Regular.ttf','fonts/Vazirmatn-Bold.ttf')

def owned(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('Unexpected installed file ownership or type: '+path.name)
    return path.read_bytes()

def digest(raw): return hashlib.sha256(raw).hexdigest()
def fingerprint(root, names):
    return digest(b'\0'.join(n.encode()+b'\0'+owned(root/n) for n in names))
def cron(): return subprocess.check_output(['crontab','-l'], timeout=15)

def atomic(path, data, mode=0o600):
    if path.is_symlink(): raise RuntimeError('Refusing a symlink target.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.chmod(name,mode); os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def build_candidate(home, runtime, revision, repo, metadata):
    old_root = home/'kiani-instagram-ranked-news-releases'/BASE
    hashes = metadata.get('news_source_hashes')
    if not isinstance(hashes,dict) or set(hashes) != set(OLD_FILES):
        raise RuntimeError('Recorded automatic-news files differ from the reviewed release.')
    sources = {}
    for name in OLD_FILES:
        raw = owned(old_root/name)
        pinned = subprocess.check_output(['git','-C',str(repo),'show',BASE+':'+name], timeout=20)
        if raw != pinned or digest(raw) != hashes[name]:
            raise RuntimeError('Installed automatic-news file differs: '+name)
        sources[name] = raw
    sources['instagram_ranked_news.py'] = owned(runtime/'deploy/instagram-trial-reels/automatic_ranked_news_images.py')
    sources['selector_trial_runtime/instagram_news_renderer.py'] = owned(runtime/'selector_trial_runtime/instagram_news_renderer.py')
    for name in EXTRA: sources[name] = owned(runtime/name)
    candidate = home/'.local/state/kiani-instagram-news-image-update/source'/revision
    if candidate.is_symlink(): raise RuntimeError('Unsafe candidate directory.')
    for name, raw in sources.items():
        path = candidate/name
        if path.is_symlink() or path.exists() and owned(path) != raw:
            raise RuntimeError('Existing candidate file differs: '+name)
        if not path.exists(): atomic(path,raw)
    return old_root, candidate, sources

def preview(home, candidate, python):
    script = candidate/'check_auto_news_images.py'
    env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul')
    subprocess.run([str(python),'-u',str(script),'--runtime',str(candidate)],
                   cwd=candidate,env=env,timeout=480,check=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime',required=True,type=Path)
    p.add_argument('--revision',required=True)
    p.add_argument('--repo',type=Path,default=Path.home()/'telegram_bot_repo')
    p.add_argument('--install',action='store_true')
    args=p.parse_args()
    if os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        raise RuntimeError('Run as the publisher user with a pinned revision.')
    os.umask(0o077)
    home, runtime = Path.home(),args.runtime.resolve()
    if runtime != (home/'.local/state/kiani-instagram-manual-news/source'/args.revision).resolve():
        raise RuntimeError('The staged manual runtime is not the pinned revision.')
    meta_path=home/'.local/state/kiani-instagram-insights/activation.json'
    old_meta=owned(meta_path); meta=json.loads(old_meta)
    if meta.get('news_runtime_revision') != BASE or meta.get('hourly_news_enabled') is not True:
        raise RuntimeError('Installed automatic-news release differs; review required.')
    if (meta.get('news_schedule',{}).get('per_slot') != 1 or
        meta.get('news_schedule',{}).get('per_category_day') != 10 or
        meta.get('policy',{}).get('assessment_hours') != 2 or
        meta.get('policy',{}).get('keep_at_or_above_views') != 200):
        raise RuntimeError('Existing news schedule or retention policy differs.')
    old_root,candidate,sources=build_candidate(home,runtime,args.revision,args.repo,meta)
    check=owned(runtime/'deploy/instagram-trial-reels/check_auto_news_images.py')
    target=candidate/'check_auto_news_images.py'
    if target.exists() and owned(target)!=check: raise RuntimeError('Candidate preflight differs.')
    if not target.exists(): atomic(target,check)
    python=home/'kiani-instagram-venv/bin/python'
    preview(home,candidate,python)
    if not args.install:
        print('Automatic-news preflight complete; no publisher was changed.')
        return
    wrappers=[home/'publish-kiani-instagram-news.sh',home/'publish-kiani-instagram-economy.sh']
    before={p:(owned(p),stat.S_IMODE(p.stat().st_mode)) for p in wrappers}
    old_ref=str(old_root/'instagram_ranked_news.py').encode()
    new_root=home/'kiani-instagram-ranked-news-releases'/args.revision
    new_ref=str(new_root/'instagram_ranked_news.py').encode()
    replacements={}
    for index,path in enumerate(wrappers):
        raw=before[path][0]
        if raw.count(old_ref) != (1 if index == 0 else 2):
            raise RuntimeError('Automatic-news launcher differs: '+path.name)
        replacements[path]=raw.replace(old_ref,new_ref)
        subprocess.run(['bash','-n'],input=replacements[path],check=True,timeout=15)
    initial_cron=cron()
    asset_hash=fingerprint(home/'kiani-instagram-publisher',ASSETS)
    locks=[meta_path.parent/'collector.lock',
           home/'.local/state/kiani-instagram-news-ranking/selection.lock',
           home/'.local/state/kiani-instagram-news-ranking/crypto.collection.lock',
           home/'.local/state/kiani-instagram-news-ranking/economy.collection.lock',
           home/'.local/state/kiani-instagram-news/news.sqlite3.lock',
           home/'.local/state/kiani-instagram-news/publisher.lock',
           home/'.local/state/kiani-instagram-economy/economy.sqlite3.lock']
    with ExitStack() as stack:
        for path in sorted(locks):
            if path.is_symlink(): raise RuntimeError('Unsafe worker lock.')
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            handle=stack.enter_context(path.open('a'))
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('A news or insights worker is active; retry shortly.') from None
        if (owned(meta_path)!=old_meta or cron()!=initial_cron or
            any(owned(p)!=before[p][0] for p in wrappers) or
            fingerprint(home/'kiani-instagram-publisher',ASSETS)!=asset_hash):
            raise RuntimeError('Installed files or schedule changed during preflight.')
        for name, raw in sources.items():
            if name not in {'instagram_ranked_news.py','selector_trial_runtime/instagram_news_renderer.py',*EXTRA}:
                if owned(old_root/name)!=raw: raise RuntimeError('Original news release changed.')
            if owned(candidate/name)!=raw: raise RuntimeError('Candidate news release changed.')
            path=new_root/name
            if path.exists() and owned(path)!=raw: raise RuntimeError('Existing immutable news release differs.')
            if not path.exists(): atomic(path,raw)
        backup=Path(tempfile.mkdtemp(prefix='kiani-auto-news-images-backup-',dir=home))
        atomic(backup/'activation.json',old_meta)
        atomic(backup/'crontab.txt',initial_cron)
        for path,(raw,mode) in before.items(): atomic(backup/path.name,raw,mode)
        runtime_names=tuple(n for n in OLD_FILES if n!='selector_trial_runtime/PINNED.md')+EXTRA
        template=dict(meta.get('news_template') or {}, revision=args.revision,
            previous_news_runtime_revision=BASE, runtime_hash=fingerprint(new_root,runtime_names),
            body_font_px=64, minimum_slide_images=2, activated_at=time.time(), backup=str(backup))
        updated=dict(meta,news_runtime_revision=args.revision,
            news_source_hashes={name:digest(owned(new_root/name)) for name in OLD_FILES+EXTRA},
            news_template=template)
        proposed=(json.dumps(updated,indent=2)+'\n').encode()
        try:
            for path,raw in replacements.items(): atomic(path,raw,before[path][1])
            atomic(meta_path,proposed)
            if cron()!=initial_cron: raise RuntimeError('Crontab changed during activation.')
        except BaseException:
            for path,raw in replacements.items():
                if path.exists() and owned(path)==raw: atomic(path,*before[path])
            if meta_path.exists() and owned(meta_path)==proposed: atomic(meta_path,old_meta)
            print('Activation incomplete; backup:',backup,flush=True)
            raise
    print('Automatic crypto and economy news image update installed:',args.revision)
    print('Two distinct images are required; additional relevant images are optional.')
    print('Existing schedules, ranking, source rules and retention are preserved.')
    print('Backup:',backup)
    print('No Instagram post was published or deleted.')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Automatic news image setup stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,flush=True)
        raise SystemExit(1)

