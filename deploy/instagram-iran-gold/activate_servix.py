#!/usr/bin/env python3
"""Add Servix to the confirmed PR68 gold runtime; optional owner-requested post."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta
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
import uuid

LEGACY_REVISION = '9c2cb58426f2c91d1b6868c732d3529b054325d9'
LEGACY = {
    'iran_gold_data.py': 'ed527d3dd027ead4ab11569f139fe7110281784cbef198b9badecbf40268b9f8',
    'iran_gold_quorum.py': 'e3c8f721e73242d23d557ec7c5d4dbf97d1406892e4657f67a12711d1c755578',
    'instagram_iran_gold.py': '96d8d21379f4756bb70f78bef737679da71254bec04d9c572815f79e77572acb',
    'instagram_iran_gold_renderer.py': '8e1d05d2aef062cbe876df9e46631317d6082db232d3d8b6c03da593f8d627d8',
    'economic_calendar_data.py': '00f19442106e1a536b160822583695d9ab00659be23d43e07c19998754247f74',
    'instagram_economic_calendar_renderer.py': '42c88b357859fa0ebb3fe5a03258be3e36cee2eee033b29afdb8e02a3a7a6219',
    'tests/test_instagram_iran_gold.py': '51fbc0e181bcf140f4c8c212c447d94fd06d1ec75fd39787a0cf1118b550aa9b',
}


def atomic(path, data, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation path.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def owned(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Expected an existing publisher-owned regular file: ' + str(path))
    return path.read_bytes()


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def wrapper(home, revision):
    python = home / 'kiani-instagram-venv/bin/python'
    script = home / 'kiani-instagram-iran-gold-releases' / revision / 'instagram_iran_gold.py'
    return ('''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONIOENCODING=utf-8
export TZ=Asia/Tehran
umask 077
set -a
. "$HOME/.kiani-instagram.env"
set +a
''' + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(script)) + ' --publish\n').encode()



def require_servix(snapshot):
    contributing = sorted({r['id'] for r in snapshot.get('rows', []) if 'servix' in r.get('sources', [])})
    if len(contributing) < 2:
        raise RuntimeError('Fresh Servix corroboration of at least two prices is required; inspect the source audit.')
    return contributing


def configure_key(home):
    import getpass
    import warnings
    from iran_gold_servix import KEY_FILE, clean_key, collect, load_key
    warnings.simplefilter('error', getpass.GetPassWarning)
    exists = KEY_FILE.exists() or KEY_FILE.is_symlink()
    original = owned(KEY_FILE) if exists else None
    key = load_key() if exists else clean_key(getpass.getpass('Servix API key (hidden; saved privately on Selenium): '))
    result = collect(key=key)
    if len(result['quotes']) < 2:
        raise RuntimeError('Servix key/source checks did not produce at least two eligible observations; no key saved.')
    try:
        with __import__('instagram_iran_gold').locked(home / '.local/state/kiani-instagram-iran-gold/publication.lock'):
            if original is None:
                if KEY_FILE.exists() or KEY_FILE.is_symlink():
                    raise RuntimeError('Servix key path appeared during configuration; nothing replaced.')
                atomic(KEY_FILE, (key + '\n').encode('ascii'), 0o600)
            elif owned(KEY_FILE) != original:
                raise RuntimeError('Servix key changed during verification.')
    finally:
        key = None
    print('Servix key: privately configured; no key value printed.')
    print('Servix per-item preflight:', json.dumps(dict(eligible=sorted(result['quotes']), excluded=result['rejected'])))
    print('Servix keeps its midpoint; excluded instruments still require other agreeing sources.')
    return 0


def post_today(home, runtime, revision, day):
    import instagram_iran_gold as app
    if day != datetime.now(app.TEHRAN).date().isoformat():
        raise RuntimeError('The one-time request is valid only on the explicitly specified Tehran day.')
    activation = json.loads(owned(app.STATE / 'activation.json'))
    if activation.get('revision') != revision or owned(home / 'publish-kiani-instagram-iran-gold.sh') != wrapper(home, revision):
        raise RuntimeError('Activate this exact reviewed gold release before its one-time post.')
    installed = home / 'kiani-instagram-iran-gold-releases' / revision
    for name in app.FILES:
        if owned(installed / name) != (runtime / name).read_bytes():
            raise RuntimeError('Installed reviewed source differs: ' + name)
    config = home / '.kiani-instagram.env'
    if config.stat().st_mode & 0o077:
        raise RuntimeError('Existing Instagram configuration must be private before publishing.')
    owned(config)  # Verify owner/regular file; never print or rewrite its contents.
    script = installed / 'instagram_iran_gold.py'
    python = home / 'kiani-instagram-venv/bin/python'
    command = 'set -euo pipefail\nset -a\n. "$HOME/.kiani-instagram.env"\nset +a\nexec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(script)) + ' --require-servix --publish-now-on ' + shlex.quote(day)
    print('Owner-requested one-time gold publication for ' + day + '; daily duplicate and fresh-price checks remain active.', flush=True)
    return subprocess.run(['/bin/bash', '-c', command], env=dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Asia/Tehran')).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--configure-key', action='store_true')
    mode.add_argument('--post-on', metavar='YYYY-MM-DD')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the reviewed revision as the publisher user, without sudo.')
    os.umask(0o077)
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    import instagram_iran_gold as app
    from iran_gold_quorum import accepted_sources
    if args.configure_key:
        return configure_key(home)
    if args.post_on:
        return post_today(home, runtime, args.revision, args.post_on)
    assets = home / 'kiani-instagram-publisher'
    app.labels(datetime.now(app.TEHRAN), assets)  # Load existing pinned calendar dependency.
    if app.next_run(datetime.now(app.TEHRAN)).utcoffset() != timedelta(hours=3, minutes=30):
        raise RuntimeError('Tehran timezone rules changed; review the gold schedule.')
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC'} or subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    for name in app.FILES:
        ast.parse((runtime / name).read_text(encoding='utf-8'), filename=name)
    launcher = home / 'publish-kiani-instagram-iran-gold.sh'
    original = owned(launcher)
    activation_path = app.STATE / 'activation.json'
    activation_original = owned(activation_path)
    active = json.loads(activation_original).get('revision')
    if active not in {LEGACY_REVISION, args.revision} or original != wrapper(home, active):
        raise RuntimeError('Installed gold release/launcher differs from the confirmed deployment; nothing replaced.')
    installed = home / 'kiani-instagram-iran-gold-releases' / active
    expected = LEGACY if active == LEGACY_REVISION else {
        name: hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in app.FILES}
    for name, digest in expected.items():
        if hashlib.sha256(owned(installed / name)).hexdigest() != digest:
            raise RuntimeError('An installed gold source file changed; nothing replaced: ' + name)
    env_path = home / '.kiani-instagram.env'
    if env_path.is_symlink() or not env_path.is_file() or env_path.stat().st_uid != os.getuid():
        raise RuntimeError('Existing private publisher configuration is unavailable.')
    story_config_path = home / '.local/state/kiani-instagram-stories/config.json'
    story_original = owned(story_config_path)
    config = json.loads(story_original)
    if (config.get('sources', {}).get('iran_gold') != str(app.STATE / 'gold.sqlite3') or
            config.get('public_root') != str(app.PUBLIC) or config.get('public_base', '').rstrip('/') != app.BASE):
        raise RuntimeError('The existing gold Story registration differs; nothing replaced.')
    story_db = Path(config['db'])
    check = sqlite3.connect(story_db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        if not check.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone():
            raise RuntimeError('The delayed Story worker is not activated.')
    finally:
        check.close()
    original_cron = cron()
    gold_jobs = []
    for line in original_cron.decode().splitlines():
        line = line.strip()
        if line.startswith('CRON_TZ=') and line.split('=', 1)[1].strip('\"\'') not in {'UTC', 'Etc/UTC'}:
            raise RuntimeError('A non-UTC CRON_TZ requires schedule review.')
        if line and not line.startswith('#') and str(launcher) in line:
            gold_jobs.append(line)
    expected_cron = f'30 6 * * * {launcher} >> {home}/kiani-instagram-iran-gold-cron.log 2>&1'
    if gold_jobs != [expected_cron]:
        raise RuntimeError('Expected exactly the confirmed daily 10:00 Tehran gold job.')
    release = home / 'kiani-instagram-iran-gold-releases' / args.revision
    for name in app.FILES:
        target, data = release / name, (runtime / name).read_bytes()
        if target.is_symlink() or target.exists() and target.read_bytes() != data:
            raise RuntimeError('An existing pinned release differs.')
        if not target.exists():
            atomic(target, data)
    with app.locked(app.STATE / 'publication.lock'):
        con = app.database(app.STATE / 'gold.sqlite3')
        try:
            preview = con.execute('''SELECT * FROM gold_previews WHERE runtime_hash=? AND assets_hash=?
                AND created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 1''',
                (app.fingerprint(runtime), app.fingerprint(assets, app.ASSETS), time.time() - 24*3600, time.time())).fetchone()
            if not preview or json.loads(preview['snapshot_json']).get('status') != 'verified':
                raise RuntimeError('A verified preview from this exact source/assets is required before activation.')
            require_servix(json.loads(preview['snapshot_json']))
            baseline = app.last_prices(con)
            snapshot = app.collect(baseline)
            audit = app.STATE / 'runs' / ('source-upgrade-' + uuid.uuid4().hex[:12] + '.json')
            atomic(audit, json.dumps(dict(snapshot=snapshot), ensure_ascii=False, indent=2).encode())
            print('Activation source audit:', audit, flush=True)
            app.validate(snapshot, baseline=baseline)
            require_servix(snapshot)
        finally:
            con.close()
        # Only the gold launcher and its metadata change. Crontab and Story
        # registration are checked for concurrent edits and are never written.
        if (owned(launcher) != original or owned(activation_path) != activation_original or
                owned(story_config_path) != story_original or cron() != original_cron):
            raise RuntimeError('Publisher configuration changed during preparation; nothing replaced.')
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-gold-servix-backup-', dir=home))
        atomic(backup / 'launcher.sh', original, launcher.stat().st_mode & 0o777)
        atomic(backup / 'activation.json', activation_original)
        atomic(backup / 'crontab.txt', original_cron)
        replacement = wrapper(home, args.revision)
        metadata = json.dumps(dict(revision=args.revision, activated_at=time.time(), preview_id=preview['id'],
            backup=str(backup), source_audit=str(audit), consensus='two-or-more-per-instrument; Servix supplementary midpoint')).encode()
        try:
            atomic(launcher, replacement, 0o700)
            atomic(activation_path, metadata)
            if cron() != original_cron or owned(story_config_path) != story_original:
                raise RuntimeError('Schedules/Story configuration changed during activation.')
        except BaseException:
            if owned(launcher) == replacement:
                atomic(launcher, original, 0o700)
            if owned(activation_path) == metadata:
                atomic(activation_path, activation_original)
            print('Source upgrade incomplete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Installed gold source revision:', args.revision)
    print('Providers: TGJU, DolarChand, Alanchand, Servix; at least two agreeing current providers per price.')
    print('Verified contributing providers:', ', '.join(accepted_sources(snapshot)))
    print('Freshness <=30min; discrepancy <=1% coins / <=0.5% gold; exact rial/toman and coherence checks retained.')
    print('Daily gold Feed remains 10:00 Asia/Tehran; Story 30 minutes after successful Feed.')
    print('Next scheduled attempt:', app.next_run(datetime.now(app.TEHRAN)).isoformat())
    print('All schedules and publication databases preserved. Insufficient agreement still skips the entire post.')
    print('Servix is one corroborating service, never the displayed source; underlying input independence is not asserted.')
    print('Activation complete. No Instagram post published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
