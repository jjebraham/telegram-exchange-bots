#!/usr/bin/env python3
"""Install the approved gold layout over the confirmed PR72 release."""
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

LEGACY_REVISION = '4d617e475a044b0f7a967bdc3ba17790b132dec2'
LEGACY = {
    'iran_gold_data.py': '292c0d816242a7332557a9987a8904f928bb62bfa22064eaf63b999f8827a4d7',
    'iran_gold_quorum.py': 'f73af63b986f9f98ca249e34db36a27aed3a6601ec5d400fda3c61048cdaa997',
    'iran_gold_servix.py': '2e1def425b2f93009e9a54e68a13ec081d06406fe6b1a45331974b272e055897',
    'instagram_iran_gold.py': 'cfc1d8306e777b05e5467c196c4e91fbe15107ad580e5511637051b5e06211d2',
    'instagram_iran_gold_renderer.py': '8e1d05d2aef062cbe876df9e46631317d6082db232d3d8b6c03da593f8d627d8',
    'economic_calendar_data.py': '00f19442106e1a536b160822583695d9ab00659be23d43e07c19998754247f74',
    'instagram_economic_calendar_renderer.py': '42c88b357859fa0ebb3fe5a03258be3e36cee2eee033b29afdb8e02a3a7a6219',
    'tests/test_instagram_iran_gold.py': '51fbc0e181bcf140f4c8c212c447d94fd06d1ec75fd39787a0cf1118b550aa9b',
    'tests/test_iran_gold_servix.py': 'e16e2303a9c852ff5493a68c3ace3fd97902b9c4c9b0b98cce206f56a44a4b86',
}


def post_test(home, runtime, revision, day):
    import instagram_iran_gold as app
    from activate_servix import owned, wrapper
    if day != datetime.now(app.TEHRAN).date().isoformat():
        raise RuntimeError('Template test is authorized only for the specified current Tehran day.')
    activation = json.loads(owned(app.STATE / 'activation.json'))
    if (activation.get('revision') != revision or activation.get('template_version') != app.TEMPLATE_VERSION or
            owned(home / 'publish-kiani-instagram-iran-gold.sh') != wrapper(home, revision)):
        raise RuntimeError('Activate this exact gold template before its manual test.')
    installed = home / 'kiani-instagram-iran-gold-releases' / revision
    for name in app.FILES:
        if owned(installed / name) != (runtime / name).read_bytes():
            raise RuntimeError('Installed gold template differs: ' + name)
    config = home / '.kiani-instagram.env'
    if config.stat().st_mode & 0o077:
        raise RuntimeError('Existing Instagram configuration must be private.')
    owned(config)  # Check ownership without displaying or rewriting credentials.
    python = home / 'kiani-instagram-venv/bin/python'
    script = installed / 'instagram_iran_gold.py'
    command = ('set -euo pipefail\nset -a\n. "$HOME/.kiani-instagram.env"\nset +a\nexec ' +
        shlex.quote(str(python)) + ' -u ' + shlex.quote(str(script)) + ' --template-test-on ' + shlex.quote(day))
    print('Owner-requested manual template test for ' + day + '; fresh prices will be collected again.', flush=True)
    print('One test per template/day; the earlier daily post and its comparison history are retained.', flush=True)
    return subprocess.run(['/bin/bash', '-c', command],
        env=dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Asia/Tehran'), check=True).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--post-on', metavar='YYYY-MM-DD')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the reviewed revision as the existing publisher user, without sudo.')
    os.umask(0o077)
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / 'deploy/instagram-iran-gold'))
    import instagram_iran_gold as app
    from activate_servix import atomic, owned, wrapper, cron
    if args.post_on:
        return post_test(home, runtime, args.revision, args.post_on)
    assets = home / 'kiani-instagram-publisher'
    app.labels(datetime.now(app.TEHRAN), assets)
    if app.next_run(datetime.now(app.TEHRAN)).utcoffset() != timedelta(hours=3, minutes=30):
        raise RuntimeError('Tehran timezone rules changed; review the gold schedule.')
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC'} or subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    for name in app.FILES:
        if name.endswith('.py'):
            ast.parse((runtime / name).read_text(encoding='utf-8'), filename=name)
    launcher = home / 'publish-kiani-instagram-iran-gold.sh'
    original = owned(launcher)
    activation_path = app.STATE / 'activation.json'
    activation_original = owned(activation_path)
    active = json.loads(activation_original).get('revision')
    if active not in {LEGACY_REVISION, args.revision} or original != wrapper(home, active):
        raise RuntimeError('Expected the confirmed Servix deployment; nothing replaced.')
    installed = home / 'kiani-instagram-iran-gold-releases' / active
    expected = LEGACY if active == LEGACY_REVISION else {
        name: hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in app.FILES}
    for name, digest in expected.items():
        if hashlib.sha256(owned(installed / name)).hexdigest() != digest:
            raise RuntimeError('An installed gold file changed; nothing replaced: ' + name)
    story_path = home / '.local/state/kiani-instagram-stories/config.json'
    story_original = owned(story_path)
    story = json.loads(story_original)
    if (story.get('sources', {}).get('iran_gold') != str(app.STATE / 'gold.sqlite3') or
            story.get('public_root') != str(app.PUBLIC) or story.get('public_base', '').rstrip('/') != app.BASE):
        raise RuntimeError('Existing gold Story registration differs.')
    check = sqlite3.connect(Path(story['db']).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        if not check.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone():
            raise RuntimeError('The delayed Story worker is not activated.')
    finally:
        check.close()
    original_cron = cron()
    jobs = []
    for line in original_cron.decode().splitlines():
        line = line.strip()
        if line.startswith('CRON_TZ=') and line.split('=', 1)[1].strip('\"\'') not in {'UTC', 'Etc/UTC'}:
            raise RuntimeError('A non-UTC cron timezone requires schedule review.')
        if line and not line.startswith('#') and str(launcher) in line:
            jobs.append(line)
    if jobs != [f'30 6 * * * {launcher} >> {home}/kiani-instagram-iran-gold-cron.log 2>&1']:
        raise RuntimeError('Expected exactly the existing daily 10:00 Tehran gold job.')
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
                (app.fingerprint(runtime), app.fingerprint(assets, app.ASSETS), time.time()-24*3600, time.time())).fetchone()
            if (not preview or json.loads(preview['snapshot_json']).get('status') != 'verified' or
                    json.loads(preview['manifest_json']).get('template_version') != app.TEMPLATE_VERSION):
                raise RuntimeError('A verified preview of this exact template, icons and fonts is required.')
            baseline = app.last_prices(con)
            snapshot = app.collect(baseline)
            audit = app.STATE / 'runs' / ('template-upgrade-' + uuid.uuid4().hex[:12] + '.json')
            atomic(audit, json.dumps(dict(snapshot=snapshot), ensure_ascii=False, indent=2).encode())
            print('Activation source audit:', audit, flush=True)
            app.validate(snapshot, baseline=baseline)
        finally:
            con.close()
        if (owned(launcher) != original or owned(activation_path) != activation_original or
                owned(story_path) != story_original or cron() != original_cron):
            raise RuntimeError('Publisher configuration changed during preparation; nothing replaced.')
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-gold-template-backup-', dir=home))
        atomic(backup / 'launcher.sh', original, launcher.stat().st_mode & 0o777)
        atomic(backup / 'activation.json', activation_original)
        atomic(backup / 'crontab.txt', original_cron)
        replacement = wrapper(home, args.revision)
        metadata = json.dumps(dict(revision=args.revision, activated_at=time.time(), preview_id=preview['id'],
            backup=str(backup), source_audit=str(audit), template_version=app.TEMPLATE_VERSION)).encode()
        try:
            atomic(launcher, replacement, 0o700)
            atomic(activation_path, metadata)
            if cron() != original_cron or owned(story_path) != story_original:
                raise RuntimeError('Schedules/Story configuration changed during activation.')
        except BaseException:
            if owned(launcher) == replacement:
                atomic(launcher, original, 0o700)
            if owned(activation_path) == metadata:
                atomic(activation_path, activation_original)
            print('Template upgrade incomplete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Installed gold template:', args.revision)
    print('Design: coin/gold headers, supplied icons, price unit in parentheses, Tehran market footer.')
    print('Daily gold Feed: 10:00 Asia/Tehran. Story: 30 minutes after successful Feed.')
    print('Next scheduled attempt:', app.next_run(datetime.now(app.TEHRAN)).isoformat())
    print('All seven fresh prices still require agreement; actual provider evidence stays in the private audit.')
    print('Activation complete. No Instagram post published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
