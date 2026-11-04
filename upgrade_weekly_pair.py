#!/usr/bin/env python3
"""Prepare and safely activate a pinned weekly Servix retry update."""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

BASE = '4745d848a1253b5c3ec39bf86a723b4c560ff8cd'
FILES = ('weekly_market_data.py','instagram_weekly_markets.py','instagram_weekly_markets_renderer.py',
         'iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py','economic_calendar_data.py',
         'instagram_economic_calendar_renderer.py','assets/instagram/gold-coin.png','assets/instagram/gold-bars.png')
CHECKS = ('test_weekly_pair_retry.py','check_weekly_pair_retry.py',
          'test_weekly_upgrade.py','upgrade_weekly_pair.py')


def owned(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('Unexpected file type or owner: '+path.name)
    return path.read_bytes()


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: '+path.name)
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def fingerprint(files):
    return hashlib.sha256(b'\0'.join(name.encode()+b'\0'+files[name] for name in FILES)).hexdigest()


def checked(root, name):
    target = root
    for part in Path(name).parts:
        target = target / part
        if target.is_symlink():
            raise RuntimeError('Refusing symlink in release path.')
    return target


def blob(repo, revision, name):
    return subprocess.check_output(['git','-C',str(repo),'show',revision+':'+name],timeout=20)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.home()/'telegram_bot_repo')
    parser.add_argument('--revision',required=True)
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    if os.geteuid()==0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        parser.error('Run as the existing publisher with the pinned revision.')
    os.umask(0o077)
    home=Path.home(); repo=args.repo.resolve()
    state=home/'.local/state/kiani-instagram-weekly-markets'
    meta_path=state/'activation.json'
    launcher=home/'publish-kiani-instagram-weekly-markets.sh'
    source=state/'source'/args.revision
    for directory in (state, state/'source', source):
        if directory.is_symlink(): raise RuntimeError('Refusing symlink state directory.')
    previous={name:blob(repo,BASE,name) for name in FILES}
    candidate={name:blob(repo,args.revision,name) for name in FILES}
    if any(candidate[name]!=previous[name] for name in FILES if name!='weekly_market_data.py'):
        raise RuntimeError('Update changes files outside the reviewed source adapter.')
    for name in FILES+CHECKS:
        raw=candidate[name] if name in candidate else blob(repo,args.revision,name)
        target=checked(source,name)
        if target.is_symlink() or target.exists() and owned(target)!=raw:
            raise RuntimeError('Existing staged file differs: '+name)
        if not target.exists(): atomic(target,raw)
    print('Pinned weekly update staged; no publication or backfill.',flush=True)
    if not args.install: return

    active_path=home/'kiani-instagram-weekly-markets-releases'/BASE
    next_path=home/'kiani-instagram-weekly-markets-releases'/args.revision
    with ExitStack() as stack:
        for lock_path in (state/'activation.lock',state/'publication.lock'):
            if lock_path.is_symlink(): raise RuntimeError('Refusing symlink lock.')
            handle=stack.enter_context(lock_path.open('a'))
            os.chmod(lock_path,0o600)
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('Weekly worker is active; retry later.') from None
        metadata_old=owned(meta_path); config=json.loads(metadata_old)
        if config.get('revision')!=BASE:
            raise RuntimeError('Active weekly revision differs from expected baseline.')
        if active_path.is_symlink() or next_path.is_symlink():
            raise RuntimeError('Refusing a symlink release directory.')
        old={name:owned(checked(active_path,name)) for name in FILES}
        if old!=previous or fingerprint(old)!=config.get('runtime_hash'):
            raise RuntimeError('Installed weekly source fingerprint differs.')
        old_launcher=owned(launcher)
        old_ref=str(active_path/'instagram_weekly_markets.py').encode()
        new_ref=str(next_path/'instagram_weekly_markets.py').encode()
        if old_launcher.count(old_ref)!=1 or b'--scheduled' not in old_launcher:
            raise RuntimeError('Installed weekly launcher differs.')
        new_launcher=old_launcher.replace(old_ref,new_ref,1)
        original_cron=subprocess.check_output(['crontab','-l'],timeout=15)
        for name in FILES:
            target=checked(next_path,name)
            if target.is_symlink() or target.exists() and owned(target)!=candidate[name]:
                raise RuntimeError('Existing release file differs: '+name)
            if not target.exists(): atomic(target,candidate[name])
        backup=Path(tempfile.mkdtemp(prefix='kiani-weekly-pair-backup-',dir=home))
        os.chmod(backup,0o700)
        atomic(backup/'activation.json',metadata_old)
        atomic(backup/'launcher.sh',old_launcher)
        config.update(revision=args.revision, runtime_hash=fingerprint(candidate),
                      previous_revision=BASE, activated_at=time.time(), backup=str(backup))
        metadata_new=json.dumps(config,ensure_ascii=False,indent=2).encode()
        if owned(meta_path)!=metadata_old or owned(launcher)!=old_launcher:
            raise RuntimeError('Weekly configuration changed during preparation.')
        if subprocess.check_output(['crontab','-l'],timeout=15)!=original_cron:
            raise RuntimeError('Crontab changed during preparation.')
        try:
            atomic(launcher,new_launcher,launcher.stat().st_mode & 0o777)
            atomic(meta_path,metadata_new)
            if owned(launcher)!=new_launcher or owned(meta_path)!=metadata_new:
                raise RuntimeError('Installed configuration failed verification.')
            if subprocess.check_output(['crontab','-l'],timeout=15)!=original_cron:
                raise RuntimeError('Crontab changed during activation.')
        except BaseException:
            if owned(launcher)==new_launcher:
                atomic(launcher,old_launcher,launcher.stat().st_mode & 0o777)
            if owned(meta_path)==metadata_new:
                atomic(meta_path,metadata_old)
            raise
    print('Weekly source retry installed:',args.revision,flush=True)
    print('Backup:',backup,flush=True)
    print('Existing schedule, comparison evidence and price checks preserved. No post published.',flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Weekly update stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,flush=True)
        raise SystemExit(1)

