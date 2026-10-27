#!/usr/bin/env python3
"""Fresh source checks and reversible, narrowly scoped publisher recovery."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from run_recovery import GOLD_FILES

BASE_GOLD = '529457456a330417bdd47e20cf8ba1590d220d5c'
RATES_HASHES = {
    'instagram_daily_rates.py': '592a28df4e47a2007da72166a7d882e0c17a75eb7926722e026a3ae3b2161d89',
    'instagram_carousel.py': '13e7d47dfaba6cee6594dba9dd4d9c67fb4dff3c621eff9a14bc07f7d2cb0d91',
    'instagram_calendar.py': '8a5ac25b3752594ba4875d68d35fd82b71bed771c035b98ddd6d5aeb4f9d3a9b',
}


def owned(path, optional=False):
    if path.is_symlink():
        raise RuntimeError('An installation path is a symlink: '+path.name)
    if not path.exists() and optional:
        return None
    info = path.stat()
    if not path.is_file() or info.st_uid != os.getuid():
        raise RuntimeError('An installation file has an unexpected owner/type: '+path.name)
    return path.read_bytes()


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def revised_cron(original, home, role):
    launcher = home/('publish-kiani-instagram-rates.sh' if role == 'rates' else 'publish-kiani-instagram-iran-gold.sh')
    hour = '8' if role == 'rates' else '6'
    lines = original.decode().splitlines(keepends=True)
    found = []
    for i, line in enumerate(lines):
        if line.strip().startswith(('CRON_TZ=', 'TZ=')) and line.strip().split('=', 1)[1].strip('\"\'') not in {'UTC', 'Etc/UTC'}:
            raise RuntimeError('A custom cron timezone requires review.')
        if line.lstrip().startswith('#') or str(launcher) not in line:
            continue
        fields = line.split()
        if fields[:5] not in (['30', hour, '*', '*', '*'], ['30,35,40', hour, '*', '*', '*']):
            raise RuntimeError('The existing '+role+' job differs from the reviewed daily schedule.')
        found.append(i)
    if len(found) != 1:
        raise RuntimeError('Expected exactly one '+role+' cron entry.')
    i = found[0]
    lines[i] = re.sub(r'^(\s*)30(?:,35,40)?(?=\s)', r'\g<1>30,35,40', lines[i], count=1)
    return ''.join(lines).encode()


def lock(stack, path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    owned(path, optional=True)
    handle = stack.enter_context(path.open('a'))
    os.chmod(path, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('A publisher is active; retry after it finishes.') from None


def rates_probe(runtime):
    # Preserve the installed optional Hawala bridge/calendar modules while the
    # candidate rates code takes precedence from the pinned staging directory.
    shared = str(Path.home()/'kiani-instagram-publisher')
    if shared not in sys.path:
        sys.path.append(shared)
    import instagram_daily_rates as rates
    from instagram_carousel import collect_sections, assert_fresh_sections
    first = rates.fetch_customer_rates()
    print('Current customer quotes verified:', json.dumps({k:str(v) for k,v in first.items()}), flush=True)
    sections = collect_sections()
    assert_fresh_sections(sections)
    rates.fetch_customer_rates()
    print('Optional rates sections currently available:', ', '.join(s['kind'] for s in sections) or 'none', flush=True)
    print('Rates check passed; customer prices were not recalculated. No Meta contact.', flush=True)


def gold_probe(runtime):
    import instagram_iran_gold as gold
    python = Path.home()/'kiani-instagram-venv/bin/python'
    subprocess.run([str(python), '-B', '-u', str(runtime/'instagram_iran_gold.py')],
                   cwd=runtime, check=True)
    # The preview must prove the new route actually contributed to the gold
    # agreement, rather than silently passing only the existing fallback pair.
    path = gold.STATE/'gold.sqlite3'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as con:
        row = con.execute('SELECT snapshot_json FROM gold_previews WHERE runtime_hash=? AND assets_hash=? '
                          'AND created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 1',
                          (gold.fingerprint(runtime), gold.fingerprint(Path.home()/'kiani-instagram-publisher', gold.ASSETS),
                           time.time()-900, time.time())).fetchone()
    snapshot = json.loads(row[0]) if row else {}
    if not any(r['id'] in {'gold18', 'mesghal'} and 'tgju' in r.get('sources', []) for r in snapshot.get('rows', [])):
        raise RuntimeError('A fresh gold preview with TGJU-confirmed gold18 or mesghal is required.')
    print('Akamai TGJU corroboration and the existing full-board checks passed. No Meta contact.', flush=True)


def activate(runtime, repo, revision, role):
    home = Path.home()
    shared = home/'kiani-instagram-publisher'
    story_config = home/'.local/state/kiani-instagram-stories/config.json'
    state = home/('.local/state/kiani-instagram-rates' if role == 'rates' else '.local/state/kiani-instagram-iran-gold')
    launcher = home/('publish-kiani-instagram-rates.sh' if role == 'rates' else 'publish-kiani-instagram-iran-gold.sh')
    old_cron, old_story, old_launcher = cron(), owned(story_config), owned(launcher)
    next_cron = revised_cron(old_cron, home, role)
    changes = {}
    proof = {}
    with ExitStack() as stack:
        lock(stack, home/'.local/state/kiani-instagram-price-recovery/activation.lock')
        lock(stack, state/('feed.json.lock' if role == 'rates' else 'publication.lock'))
        if role == 'rates':
            for name, expected in RATES_HASHES.items():
                old = owned(shared/name)
                new = owned(runtime/name) if name == 'instagram_daily_rates.py' else old
                if hashlib.sha256(old).hexdigest() != expected and old != new:
                    raise RuntimeError('An installed rates file differs: '+name)
                if name != 'instagram_daily_rates.py' and hashlib.sha256(old).hexdigest() != expected:
                    raise RuntimeError('An installed rates layout differs: '+name)
                if name == 'instagram_daily_rates.py':
                    changes[shared/name] = (old, new, (shared/name).stat().st_mode & 0o777)
            receipt = Path(str(state/'feed.json')+'.publication.json')
            raw = owned(receipt, optional=True)
            if raw is not None and json.loads(raw).get('status') != 'published':
                raise RuntimeError('An uncertain rates publication needs reconciliation before activation.')
            metadata_path = state/'recovery.json'
            metadata_old = owned(metadata_path, optional=True)
        else:
            import instagram_iran_gold as gold
            sys.path.insert(0, str(runtime/'deploy/instagram-iran-gold'))
            from activate_servix import wrapper
            metadata_path = state/'activation.json'
            metadata_old = owned(metadata_path)
            active = json.loads(metadata_old).get('revision')
            if active not in {BASE_GOLD, revision} or old_launcher != wrapper(home, active):
                raise RuntimeError('The installed gold launcher/revision differs from the confirmed release.')
            installed = home/'kiani-instagram-iran-gold-releases'/active
            old_files = [n for n in GOLD_FILES if n != 'iran_gold_tgju.py'] if active == BASE_GOLD else GOLD_FILES
            for name in old_files:
                expected = subprocess.check_output(['git', '-C', str(repo), 'show', BASE_GOLD+':'+name], timeout=20) if active == BASE_GOLD else owned(runtime/name)
                if owned(installed/name) != expected:
                    raise RuntimeError('An installed gold file changed: '+name)
            con = sqlite3.connect((state/'gold.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)
            try:
                baseline = gold.last_prices(con)
            finally:
                con.close()
            gold.labels(datetime.now(gold.TEHRAN), shared)
            snapshot = gold.collect(baseline)
            gold.validate(snapshot, baseline=baseline)
            if not any(r['id'] in {'gold18', 'mesghal'} and 'tgju' in r['sources'] for r in snapshot['rows']):
                raise RuntimeError('Fresh activation prices lack TGJU gold corroboration.')
            audit = state/'runs'/('source-recovery-'+uuid.uuid4().hex[:12]+'.json')
            atomic(audit, json.dumps(dict(snapshot=snapshot), ensure_ascii=False, indent=2).encode())
            proof['source_audit'] = str(audit)
            con = sqlite3.connect((state/'gold.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)
            try:
                preview = con.execute('SELECT id FROM gold_previews WHERE runtime_hash=? AND assets_hash=? '
                    'AND created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 1',
                    (gold.fingerprint(runtime), gold.fingerprint(shared, gold.ASSETS), time.time()-900, time.time())).fetchone()
            finally:
                con.close()
            if not preview:
                raise RuntimeError('The matching gold preview expired before activation.')
            proof['preview_id'] = preview[0]
            release = home/'kiani-instagram-iran-gold-releases'/revision
            for name in GOLD_FILES:
                target, data = release/name, owned(runtime/name)
                if target.exists() and owned(target) != data or target.is_symlink():
                    raise RuntimeError('A pinned gold release file differs.')
                if not target.exists():
                    atomic(target, data)
            changes[launcher] = (old_launcher, wrapper(home, revision), 0o700)
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-'+role+'-recovery-backup-', dir=home))
        backup.chmod(0o700)
        atomic(backup/'crontab.txt', old_cron)
        for path, (old, _, _) in changes.items():
            atomic(backup/path.name, old)
        if metadata_old is not None:
            atomic(backup/metadata_path.name, metadata_old)
        previous_metadata = json.loads(metadata_old) if metadata_old else {}
        metadata = json.dumps(dict(previous_metadata, **proof, revision=revision, activated_at=time.time(), backup=str(backup),
            role=role, first_attempt='12:00 Tehran' if role == 'rates' else '10:00 Tehran',
            retries_minutes=[5,10], tgju_transport='fixed Akamai tgju_current' if role == 'gold' else None)).encode()
        if cron() != old_cron or owned(story_config) != old_story or owned(launcher) != old_launcher:
            raise RuntimeError('Publisher settings changed during preparation.')
        if owned(metadata_path, optional=True) != metadata_old:
            raise RuntimeError('Activation metadata changed during preparation.')
        changed = []
        try:
            for path, (old, new, mode) in changes.items():
                if owned(path) != old:
                    raise RuntimeError('An installation file changed concurrently.')
                atomic(path, new, mode); changed.append(path)
            atomic(metadata_path, metadata)
            subprocess.run(['crontab', '-'], input=next_cron, check=True, timeout=15)
            if cron() != next_cron or owned(story_config) != old_story:
                raise RuntimeError('Schedules or Story registration changed during activation.')
            for path, (_, new, _) in changes.items():
                if owned(path) != new:
                    raise RuntimeError('Installed source verification failed.')
        except BaseException:
            if next_cron != old_cron and cron() == next_cron:
                subprocess.run(['crontab', '-'], input=old_cron, check=True, timeout=15)
            for path in reversed(changed):
                old, new, mode = changes[path]
                if owned(path) == new:
                    atomic(path, old, mode)
            if owned(metadata_path, optional=True) == metadata:
                if metadata_old is None:
                    metadata_path.unlink()
                else:
                    atomic(metadata_path, metadata_old)
            raise
    print('Backup:', backup, flush=True)
    print('Installed '+role+' recovery:', revision, flush=True)
    print('Daily attempts: '+('12:00, 12:05, 12:10' if role == 'rates' else '10:00, 10:05, 10:10')+' Tehran.', flush=True)
    print('At most one successful daily Feed; existing Story follows success +30 minutes.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--target', choices=('both', 'rates', 'gold'), default='both')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the reviewed revision as the existing publisher user.')
    os.umask(0o077)
    runtime = args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    for path in runtime.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3,11))
    if args.activate:
        zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
        if zone not in {'UTC','Etc/UTC'} or subprocess.run(['systemctl','is-active','--quiet','cron'],timeout=15).returncode:
            raise RuntimeError('Expected the existing active UTC cron service.')
    failures = []
    for role in ('rates', 'gold') if args.target == 'both' else (args.target,):
        try:
            print('\nChecking '+role+' with fresh sources. No publishing or deletion.', flush=True)
            (rates_probe if role == 'rates' else gold_probe)(runtime)
            if args.activate:
                activate(runtime, args.repo.resolve(), args.revision, role)
        except Exception as exc:
            failures.append(role)
            print(role+' recovery stopped: '+(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), flush=True)
    print('No Instagram post was published or deleted by this command.', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Recovery stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
