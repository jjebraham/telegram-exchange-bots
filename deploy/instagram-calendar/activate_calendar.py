#!/usr/bin/env python3
"""Install the reviewed weekly calendar and add its existing-worker Story source."""
from __future__ import annotations

import argparse
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

LEGACY = {'instagram_delayed_stories.py': '4306a728dc7302f7639f8f4b373e0262a22ac97d10f2dfcc552672754f9747b0',
          'instagram_story_renderer.py': '434042b46ed58a188009eefa57be8c2b2570d98fd11cb171f8eb1db22c99bd46'}
BEGIN, END = '# BEGIN Kiani weekly economic calendar', '# END Kiani weekly economic calendar'


def atomic(path, data, mode):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation path.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the publisher user without sudo, using the reviewed revision.')
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    import instagram_economic_calendar as app
    assets = home / 'kiani-instagram-publisher'
    from instagram_economic_calendar_renderer import labels
    now = datetime.now(app.TEHRAN)
    start, _ = app.window(now)
    if start.utcoffset() != timedelta(hours=3, minutes=30):
        raise RuntimeError('Tehran timezone rules changed; review the UTC schedule before installation.')
    labels(start, assets)  # Import the already-installed pinned Persian calendar library.
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC'} or subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('An active UTC cron service is required.')
    con = app.database(app.STATE / 'calendar.sqlite3')
    try:
        reviewed = con.execute('''SELECT * FROM calendar_previews WHERE runtime_hash=? AND assets_hash=?
            AND created_at BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 1''',
            (app.fingerprint(runtime), app.fingerprint(assets, app.ASSETS), time.time() - 48 * 3600, time.time())).fetchone()
        if not reviewed:
            raise RuntimeError('Run and review a successful live calendar preview from this exact runtime before activation.')
        app.validate(json.loads(reviewed['snapshot_json']))
    finally:
        con.close()
    private_env = home / '.kiani-instagram.env'
    if private_env.is_symlink() or not private_env.is_file() or private_env.stat().st_uid != os.getuid():
        raise RuntimeError('Existing private publisher configuration is missing or has an unexpected owner.')
    python = home / 'kiani-instagram-venv/bin/python'
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError('The existing publisher Python runtime is unavailable.')
    story_root = home / 'kiani-instagram-story-publisher'
    config_path = home / '.local/state/kiani-instagram-stories/config.json'
    if config_path.is_symlink() or not config_path.is_file() or config_path.stat().st_uid != os.getuid():
        raise RuntimeError('Existing Story configuration is missing or has an unexpected owner.')
    original_config = config_path.read_bytes()
    config = json.loads(original_config)
    if not {'rates', 'economy', 'top50', 'crypto'} <= set(config['sources']):
        raise RuntimeError('Existing Story sources differ from the reviewed setup.')
    if config['public_root'] != str(app.PUBLIC) or config['public_base'].rstrip('/') != app.BASE:
        raise RuntimeError('Existing public media directory differs; review before activation.')
    source = str(app.STATE / 'calendar.sqlite3')
    if config['sources'].get('calendar', source) != source:
        raise RuntimeError('A different calendar source is already installed.')
    config['sources']['calendar'] = source
    story_db = Path(config['db'])
    check = sqlite3.connect(story_db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        if not check.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone():
            raise RuntimeError('The existing delayed Story queue is not activated.')
    finally:
        check.close()
    release = home / 'kiani-instagram-economic-calendar-releases' / args.revision
    for name in app.FILES:
        path, data = release / name, (runtime / name).read_bytes()
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing versioned calendar runtime differs.')
        if not path.exists():
            atomic(path, data, 0o600)
    launcher = home / 'publish-kiani-instagram-calendar.sh'
    python = home / 'kiani-instagram-venv/bin/python'
    wrapper = ('''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONIOENCODING=utf-8
export TZ=Asia/Tehran
umask 077
set -a
. "$HOME/.kiani-instagram.env"
set +a
''' + 'exec ' + shlex.quote(str(python)) + ' -u ' + shlex.quote(str(release / 'instagram_economic_calendar.py')) + ' --publish\n').encode()
    changed = {launcher: (wrapper, 0o700), config_path: (json.dumps(config, indent=2).encode() + b'\n', 0o600)}
    for name, legacy_hash in LEGACY.items():
        path, new = story_root / name, (runtime / name).read_bytes()
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            raise RuntimeError('An expected Story worker file is missing or has an unexpected owner.')
        if path.read_bytes() != new and hashlib.sha256(path.read_bytes()).hexdigest() != legacy_hash:
            raise RuntimeError('The installed Story worker differs from the reviewed revision; nothing replaced.')
        changed[path] = new, path.stat().st_mode & 0o777
    before = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in changed}
    if any(p.is_symlink() for p in changed):
        raise RuntimeError('Refusing symlink replacement.')
    with ExitStack() as stack:
        for path in sorted((app.STATE / 'publication.lock', story_db.with_suffix('.lock'))):
            handle = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A publisher is active; retry activation after it finishes.') from None
        if config_path.read_bytes() != original_config or any(p.exists() != bool(old) or old and p.read_bytes() != old[0] for p, old in before.items()):
            raise RuntimeError('Publisher files changed during preparation; nothing replaced.')
        original = cron()
        command = f'30 6 * * 6 {launcher} >> {home}/kiani-instagram-calendar-cron.log 2>&1'
        kept = []
        for line in original.decode().splitlines():
            stripped = line.strip()
            if stripped.startswith('CRON_TZ=') and stripped.split('=', 1)[1].strip('"\'') not in {'UTC', 'Etc/UTC'}:
                raise RuntimeError('A non-UTC CRON_TZ needs review before installation.')
            if stripped in {BEGIN, END}:
                continue
            if str(launcher) in line and not stripped.startswith('#'):
                if stripped != command:
                    raise RuntimeError('An existing calendar cron command differs; nothing replaced.')
                continue
            kept.append(line)
        replacement = ('\n'.join(kept).rstrip() + '\n\n' + BEGIN + '\n' + command + '\n' + END + '\n').encode()
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-calendar-weekly-backup-', dir=home))
        (backup / 'crontab.txt').write_bytes(original)
        (backup / 'paths.json').write_text(json.dumps([str(p) for p in before]))
        for i, (p, old) in enumerate(before.items()):
            if old:
                (backup / str(i)).write_bytes(old[0])
        installed = False
        try:
            if cron() != original:
                raise RuntimeError('Crontab changed during preparation.')
            for p, (data, mode) in changed.items():
                atomic(p, data, mode)
            if cron() != original:
                raise RuntimeError('Crontab changed during installation.')
            subprocess.run(['crontab', '-'], input=replacement, capture_output=True, check=True, timeout=15)
            installed = True
            if cron() != replacement:
                raise RuntimeError('Installed weekly schedule did not match.')
            atomic(app.STATE / 'activation.json', json.dumps(dict(revision=args.revision, activated_at=time.time(),
                preview_id=reviewed['id'], backup=str(backup))).encode(), 0o600)
        except BaseException:
            for p, old in before.items():
                if p.exists() and p.read_bytes() == changed[p][0]:
                    if old:
                        atomic(p, *old)
                    else:
                        p.unlink()
            if installed and cron() == replacement:
                subprocess.run(['crontab', '-'], input=original, check=True, capture_output=True, timeout=15)
            print('Activation incomplete. Backup:', backup, file=sys.stderr)
            raise
    next_run = start if start > now else start + timedelta(days=7)
    print('Backup:', backup)
    print('Weekly Feed: Saturday 10:00 Asia/Tehran (06:30 UTC).')
    print('Next scheduled post:', next_run.isoformat())
    print('Story: 30 minutes after successful Feed publication, through the existing worker.')
    print('Event times: Tehran; Persian and Gregorian dates; fresh official calendars each week.')
    print('Existing daily Feed schedules, publication databases and queued Stories preserved.')
    print('Activation complete. No Instagram post published during installation.')
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        raise SystemExit(1)
