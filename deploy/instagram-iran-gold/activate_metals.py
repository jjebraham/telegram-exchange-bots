#!/usr/bin/env python3
"""Install verified global metals over the confirmed PR73 gold template."""
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

LEGACY_REVISION = '23f3aa27f764100cc74fe45e03e629b05df2ddb2'
LEGACY = {
    'iran_gold_data.py': '292c0d816242a7332557a9987a8904f928bb62bfa22064eaf63b999f8827a4d7',
    'iran_gold_quorum.py': 'f73af63b986f9f98ca249e34db36a27aed3a6601ec5d400fda3c61048cdaa997',
    'iran_gold_servix.py': '2e1def425b2f93009e9a54e68a13ec081d06406fe6b1a45331974b272e055897',
    'instagram_iran_gold.py': 'bd0531564d6f0939b970197010a0141326facd047e1ab109e26b06063d103459',
    'instagram_iran_gold_renderer.py': '8dfc34304196fb44d212788d7e809c177d1433e06ff68403a046ccd0614c9eec',
    'economic_calendar_data.py': '00f19442106e1a536b160822583695d9ab00659be23d43e07c19998754247f74',
    'instagram_economic_calendar_renderer.py': '42c88b357859fa0ebb3fe5a03258be3e36cee2eee033b29afdb8e02a3a7a6219',
    'tests/test_instagram_iran_gold.py': '51fbc0e181bcf140f4c8c212c447d94fd06d1ec75fd39787a0cf1118b550aa9b',
    'tests/test_iran_gold_servix.py': 'e16e2303a9c852ff5493a68c3ace3fd97902b9c4c9b0b98cce206f56a44a4b86',
    'tests/test_iran_gold_template.py': '3235a48e235cd02119968847623c537400f5513fc617d5948859345ddf38b7ff',
    'deploy/instagram-iran-gold/activate_servix.py': '7df5d26526d7b9e5b5846bec2f668c4de47d36dcb999062e03352d76ea885cdc',
    'deploy/instagram-iran-gold/activate_template.py': 'b2f29ff794f9a04249a30af336d2e651b0f2934f3a384a3f448b036ab45a1c38',
    'assets/instagram/gold-coin.png': 'a20779c0ef961545392673efc46d47d42226bf40a64cbf319eca21c6b4a2c8b6',
    'assets/instagram/gold-bars.png': '6b263395f2733a589cca2a596b344c60cc13a8149ae2e729af587cc98ad2adf8',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the reviewed revision as the existing publisher user, without sudo.')
    os.umask(0o077)
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / 'deploy/instagram-iran-gold'))
    import instagram_iran_gold as app
    from activate_servix import atomic, owned, wrapper, cron
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
        raise RuntimeError('Expected the confirmed PR73 gold deployment; nothing replaced.')
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
            saved = json.loads(preview['snapshot_json']) if preview else {}
            shown = json.loads(preview['manifest_json']) if preview else {}
            if (saved.get('status') != 'verified' or saved.get('global_metals',{}).get('status') != 'verified' or
                    shown.get('global_metals_version') != app.global_metals.VERSION or len(shown.get('images',[])) != 2):
                raise RuntimeError('A verified TWO-slide preview of this exact runtime/icons/fonts is required.')
            baseline = app.last_prices(con)
            snapshot = app.collect(baseline)
            snapshot['global_metals'] = app.global_metals.collect()
            audit = app.STATE / 'runs' / ('global-metals-upgrade-' + uuid.uuid4().hex[:12] + '.json')
            atomic(audit, json.dumps(dict(snapshot=snapshot), ensure_ascii=False, indent=2).encode())
            print('Activation source audit:', audit, flush=True)
            app.validate(snapshot, baseline=baseline)
            app.global_metals.validate(snapshot['global_metals'])
        finally:
            con.close()
        if (owned(launcher) != original or owned(activation_path) != activation_original or
                owned(story_path) != story_original or cron() != original_cron):
            raise RuntimeError('Publisher configuration changed during preparation; nothing replaced.')
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-global-metals-backup-', dir=home))
        atomic(backup / 'launcher.sh', original, launcher.stat().st_mode & 0o777)
        atomic(backup / 'activation.json', activation_original)
        atomic(backup / 'crontab.txt', original_cron)
        replacement = wrapper(home, args.revision)
        metadata = json.dumps(dict(revision=args.revision, activated_at=time.time(), preview_id=preview['id'],
            backup=str(backup), source_audit=str(audit), template_version=app.TEMPLATE_VERSION,
            global_metals_version=app.global_metals.VERSION, global_metals_sources='Servix observation plus one or more matching publishers')).encode()
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
            print('Global-metals upgrade incomplete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Installed gold/global-metals carousel:', args.revision)
    print('Slide 1: Iran gold and coins. Slide 2: global gold/silver, USD per troy ounce, verified ratio.')
    print('Daily Feed: 10:00 Asia/Tehran. Existing Story uses the first slide 30 minutes after successful Feed.')
    print('Next scheduled attempt:', app.next_run(datetime.now(app.TEHRAN)).isoformat())
    print('Global slide requires fresh Servix business times plus a matching publisher; <=0.5% price gap and <=10min clock skew.')
    print('Stale/unavailable global quotes omit slide 2; a verified Iran board can still publish. Invalid Iran prices skip the entire post.')
    print('Daily/weekly global changes populate from verified successful publication history; missing comparisons stay blank.')
    print('Activation complete. No Instagram post published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
