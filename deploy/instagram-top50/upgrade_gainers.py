#!/usr/bin/env python3
"""Upgrade the existing top 50 publisher without changing jobs or posting immediately."""
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
from zoneinfo import ZoneInfo

from activate_top50_cron import WRAPPER

LEGACY = {
    'crypto_top50_data.py': 'f00cdf55220e7cc088948634c571bb0f2f224dbff063e881f4855066191f24d4',
    'instagram_top50_prices.py': 'aaaf133b87dc3a57f42e43470195d54a1944e7f891afe786c01ff29a9f7fed07',
    'instagram_top50_renderer.py': '146f861ef8858791305199b195639ab143a2a28c670fc27c1f9a8bc3ec6f1acb',
}


def owned(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Expected a publisher-owned regular file: ' + str(path))
    return path.read_bytes()


def atomic(path, data, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation target.')
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


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the publisher user without sudo, using the reviewed revision.')
    os.umask(0o077)
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    import instagram_top50_prices as app
    from crypto_top50_data import collect, validate_snapshot
    assets = home / 'kiani-instagram-publisher'
    for name in app.RUNTIME_FILES:
        ast.parse((runtime / name).read_text(encoding='utf-8'), filename=name)
    for path in (home / '.kiani-instagram.env', app.DEFAULT_DB):
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            raise RuntimeError('An existing publisher prerequisite is missing: ' + str(path))
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC', 'GMT', 'Etc/GMT'} or subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The existing active UTC cron service is required.')
    now = datetime.now(ZoneInfo('Europe/Istanbul'))
    start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    if start.utcoffset() != timedelta(hours=3):
        raise RuntimeError('Istanbul timezone rules changed; review the existing UTC schedule.')
    original_cron = cron()
    launcher = home / 'publish-kiani-instagram-top50.sh'
    jobs = []
    for line in original_cron.decode().splitlines():
        line = line.strip()
        if line.startswith('CRON_TZ=') and line.split('=', 1)[1].strip('\"\'') not in {'UTC', 'Etc/UTC', 'GMT', 'Etc/GMT', ''}:
            raise RuntimeError('A non-UTC CRON_TZ needs review.')
        if line and not line.startswith('#') and str(launcher) in line:
            jobs.append(line)
    if jobs != [f'0 13 * * * {launcher} publish >> {home}/kiani-instagram-top50-cron.log 2>&1']:
        raise RuntimeError('Expected exactly the existing 16:00 Istanbul top 50 job.')
    config_path = home / '.local/state/kiani-instagram-stories/config.json'
    original_config = owned(config_path)
    config = json.loads(original_config)
    if config.get('sources', {}).get('top50') != str(app.DEFAULT_DB):
        raise RuntimeError('The existing top 50 Story registration differs.')
    original = owned(launcher)
    metadata_path = app.DEFAULT_DB.parent / 'gainers-activation.json'
    original_metadata = owned(metadata_path) if metadata_path.exists() else None
    release = home / 'kiani-instagram-top50-releases' / args.revision
    old_wrapper = WRAPPER.encode()
    marker = b'"$HOME/kiani-instagram-top50-publisher/instagram_top50_prices.py"'
    if old_wrapper.count(marker) != 1 or hashlib.sha256(old_wrapper).hexdigest() != '14d1ed4a6d30577c53c8257178d233f417892d5158680fc73e6fe8073bdbae33':
        raise RuntimeError('The reviewed legacy launcher template changed.')
    replacement = old_wrapper.replace(marker, shlex.quote(str(release / 'instagram_top50_prices.py')).encode())
    if original == old_wrapper:
        for name, digest in LEGACY.items():
            if hashlib.sha256(owned(home / 'kiani-instagram-top50-publisher' / name)).hexdigest() != digest:
                raise RuntimeError('An installed top 50 source differs from the confirmed release: ' + name)
    elif (original != replacement or not original_metadata or
          json.loads(original_metadata).get('revision') != args.revision):
        raise RuntimeError('Installed top 50 launcher differs; nothing replaced.')
    subprocess.run(['bash', '-n'], input=replacement, check=True, timeout=15)
    for name in app.RUNTIME_FILES:
        target, data = release / name, (runtime / name).read_bytes()
        if target.is_symlink() or target.exists() and target.read_bytes() != data:
            raise RuntimeError('An existing pinned top 50 release differs.')
        if not target.exists():
            atomic(target, data)
    with app.run_lock(app.DEFAULT_DB):
        con = sqlite3.connect(app.DEFAULT_DB.resolve().as_uri() + '?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        try:
            runtime_hash = app.fingerprint(runtime, app.RUNTIME_FILES)
            assets_hash = app.fingerprint(assets, app.SHARED_FILES)
            preview = None
            for row in con.execute('SELECT * FROM top50_snapshots WHERE created_at BETWEEN ? AND ? ORDER BY created_at DESC',
                                   (time.time()-24*3600, time.time())):
                manifest = json.loads(row['manifest_json'])
                if (manifest.get('top50_runtime_fingerprint') == runtime_hash and
                        manifest.get('shared_assets_fingerprint') == assets_hash and not manifest.get('sample') and
                        manifest.get('sections') == ['gainers'] + ['top50']*5 and len(manifest.get('images', [])) == 6):
                    snapshot = json.loads(row['data_json'])
                    validate_snapshot(snapshot)
                    preview = row['id']
                    break
            if not preview:
                raise RuntimeError('Run a verified six-slide preview from this exact runtime/assets before activation.')
        finally:
            con.close()
        # A new source-only check is required; a historical preview never
        # authorizes reuse of its prices for the next scheduled publication.
        snapshot = collect()
        validate_snapshot(snapshot, publishing=True)
        audit = app.DEFAULT_DB.parent / 'runs' / ('gainers-activation-' + uuid.uuid4().hex[:12] + '.json')
        atomic(audit, json.dumps(snapshot, ensure_ascii=False, indent=2).encode())
        if (owned(launcher) != original or cron() != original_cron or owned(config_path) != original_config or
                (owned(metadata_path) if metadata_path.exists() else None) != original_metadata or
                app.fingerprint(assets, app.SHARED_FILES) != assets_hash):
            raise RuntimeError('Publisher files/assets/schedules changed during preparation; nothing replaced.')
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-gainers-backup-', dir=home))
        atomic(backup / 'launcher.sh', original, launcher.stat().st_mode & 0o777)
        atomic(backup / 'crontab.txt', original_cron)
        if original_metadata:
            atomic(backup / 'gainers-activation.json', original_metadata)
        metadata = json.dumps(dict(revision=args.revision, activated_at=time.time(),
            preview_id=preview, runtime_hash=runtime_hash, assets_hash=assets_hash,
            source_audit=str(audit), backup=str(backup))).encode()
        try:
            atomic(launcher, replacement, 0o700)
            atomic(metadata_path, metadata)
            if cron() != original_cron or owned(config_path) != original_config:
                raise RuntimeError('Schedules/Story registration changed during activation.')
        except BaseException:
            if owned(launcher) == replacement:
                atomic(launcher, original, 0o700)
            if metadata_path.exists() and owned(metadata_path) == metadata:
                if original_metadata:
                    atomic(metadata_path, original_metadata)
                else:
                    metadata_path.unlink()
            print('Activation incomplete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Installed gainers revision:', args.revision)
    print('Feed: daily 16:00 Europe/Istanbul; six slides: gainers first, then five top 50 price slides.')
    print('Gainers: up to ten positive 24h USD changes among the global top 100; volume > USD 50,000; CoinPaprika.')
    print('Story: first-slide gainers preview, 30 minutes after successful Feed publication.')
    print('Next scheduled attempt:', start.isoformat())
    print('Existing publication history, duplicate guards and all other schedules preserved.')
    print('Activation complete. No Instagram post published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
