#!/usr/bin/env python3
"""Activate the reviewed top 50 cryptocurrency carousel at 16:00 Istanbul daily."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
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
from zoneinfo import ZoneInfo

FILES = ('instagram_top50_prices.py', 'crypto_top50_data.py', 'instagram_top50_renderer.py')
SHARED_FILES = ('instagram_daily_rates.py', 'assets/instagram/kiani-logo.svg',
                'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')
BEGIN = '# BEGIN Kiani Instagram top 50 prices'
END = '# END Kiani Instagram top 50 prices'
WRAPPER = r'''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 022
action=${1:-publish}
if [ "$action" != publish ]; then
  printf 'Use publish.\n' >&2; exit 2
fi
set -a
. "$HOME/.kiani-instagram.env"
set +a
printf '%s Starting top 50 prices (%s).\n' "$(date -Is)" "$action"
if "$HOME/kiani-instagram-venv/bin/python" -u \
  "$HOME/kiani-instagram-top50-publisher/instagram_top50_prices.py" \
  --publisher-root "$HOME/kiani-instagram-publisher" \
  --db "$HOME/.local/state/kiani-instagram-top50/top50.sqlite3" \
  --output /var/www/peerexo.com/public/instagram-rates/top50 \
  --public-base https://peerexo.com/instagram-rates/top50 --publish; then
  printf '%s Top 50 prices completed (%s).\n' "$(date -Is)" "$action"
else
  result=$?
  printf '%s Top 50 prices failed (%s, exit %s).\n' "$(date -Is)" "$action" "$result" >&2
  exit "$result"
fi
'''


class ActivationError(RuntimeError):
    pass


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def cron_read():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ActivationError('Could not read the existing crontab; no schedules replaced.')
    return result.stdout


def without_managed_block(cron):
    lines, inside = [], False
    for line in cron.splitlines(keepends=True):
        if line.strip() == BEGIN:
            if inside:
                raise ActivationError('Duplicate top 50 cron marker.')
            inside = True
        elif line.strip() == END:
            if not inside:
                raise ActivationError('Top 50 cron end marker has no beginning.')
            inside = False
        elif not inside:
            if 'publish-kiani-instagram-top50.sh' in line and not line.lstrip().startswith('#'):
                raise ActivationError('An unmanaged top 50 job needs review before replacement.')
            lines.append(line)
    if inside:
        raise ActivationError('Top 50 cron block is incomplete.')
    return ''.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True, help='Exact tested 40-character Git commit SHA')
    parser.add_argument('--at', default='16:00', help='Daily Istanbul time HH:MM, default 16:00')
    parser.add_argument('--approved-media-id', required=True, help='Media ID from the reviewed manual top 50 post')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise ActivationError('Run on Selenium as the existing publisher user, without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision) or not re.fullmatch(r'\d+', args.approved_media_id):
        raise ActivationError('Supply the exact tested revision and manual Instagram media ID.')
    try:
        hour, minute = map(int, args.at.split(':'))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError()
    except ValueError:
        raise ActivationError('Daily time must be HH:MM in Istanbul.') from None
    home, repo = Path.home().resolve(), args.repo.expanduser().resolve()
    root = home / 'kiani-instagram-top50-publisher'
    wrapper = home / 'publish-kiani-instagram-top50.sh'
    db = home / '.local/state/kiani-instagram-top50/top50.sqlite3'
    now = datetime.now(ZoneInfo('Europe/Istanbul'))
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    utc_run = next_run.astimezone(timezone.utc)
    env = dict(os.environ)
    env.pop('TZ', None)
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'],
                                   text=True, env=env, timeout=20).strip()
    if zone not in {'UTC', 'Etc/UTC', 'GMT', 'Etc/GMT'}:
        raise ActivationError('The existing server must use the confirmed UTC timezone.')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=20).returncode:
        raise ActivationError('Cron must be active.')
    required = [db, home / '.kiani-instagram.env', home / 'kiani-instagram-venv/bin/python',
                home / 'kiani-instagram-publisher/instagram_daily_rates.py',
                home / 'kiani-instagram-publisher/assets/instagram/kiani-logo.svg',
                home / 'kiani-instagram-publisher/fonts/Vazirmatn-Regular.ttf',
                home / 'kiani-instagram-publisher/fonts/Vazirmatn-Bold.ttf']
    for path in required:
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ActivationError(f'Missing existing manual-test prerequisite: {path}')
    output = Path('/var/www/peerexo.com/public/instagram-rates/top50')
    if not output.is_dir() or not os.access(output, os.W_OK):
        raise ActivationError('The public top 50 image directory must already be writable from the manual test.')
    files = {}
    for name in FILES:
        data = subprocess.check_output(['git', '-C', str(repo), 'show', f'{args.revision}:{name}'], timeout=20)
        compile(data, name, 'exec')
        files[root / name] = (data, 0o644)
    fingerprint = hashlib.sha256(b'\0'.join(name.encode() + b'\0' + files[root / name][0] for name in FILES)).hexdigest()
    con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    try:
        row = con.execute("SELECT manifest_json FROM top50_publications WHERE media_id=? AND status='published'",
                          (args.approved_media_id,)).fetchone()
    finally:
        con.close()
    if not row or json.loads(row[0]).get('top50_runtime_fingerprint') != fingerprint:
        raise ActivationError('This runtime has no matching successful manual top 50 post; test and review it first.')
    shared_root = home / 'kiani-instagram-publisher'
    shared_hash = hashlib.sha256(b'\0'.join(name.encode() + b'\0' + (shared_root / name).read_bytes() for name in SHARED_FILES)).hexdigest()
    if json.loads(row[0]).get('shared_assets_fingerprint') != shared_hash:
        raise ActivationError('The shared publisher or brand assets changed after the manual post; review a new manual post first.')
    files[root / 'revision.txt'] = ((args.revision + '\n').encode(), 0o644)
    files[root / 'NOTICE'] = (subprocess.check_output([
        'git', '-C', str(repo), 'show', f'{args.revision}:deploy/instagram-top50/NOTICE'], timeout=20), 0o644)
    files[wrapper] = (WRAPPER.encode(), 0o700)
    subprocess.run(['bash', '-n'], input=WRAPPER, text=True, check=True, timeout=20)
    original_cron = cron_read()
    for line in original_cron.splitlines():
        match = re.match(r'^\s*CRON_TZ\s*=\s*(.*?)\s*$', line)
        if match and match.group(1).strip('\"\'') not in {'', 'UTC', 'Etc/UTC', 'GMT', 'Etc/GMT'}:
            raise ActivationError('Non-UTC CRON_TZ needs review.')
    kept = without_managed_block(original_cron).rstrip('\n')
    log = shlex.quote(str(home / 'kiani-instagram-top50-cron.log'))
    command = shlex.quote(str(wrapper))
    block = (f'{BEGIN}\n{utc_run.minute} {utc_run.hour} * * * {command} publish >> {log} 2>&1\n{END}\n')
    updated = (kept + '\n' if kept else '') + block
    backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-top50-backup-', dir=home))
    backup.chmod(0o700)
    original, changed = {}, []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(home):
            raise ActivationError(f'Unexpected installation target: {path}')
        saved = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        original[path] = saved
        if saved:
            atomic_write(backup / path.relative_to(home), saved[0], 0o600)
    atomic_write(backup / 'crontab.txt', original_cron.encode(), 0o600)
    print(f'Backup: {backup}', flush=True)
    attempted = False
    try:
        for path, (data, mode) in files.items():
            changed.append(path)
            atomic_write(path, data, mode)
        if cron_read() != original_cron:
            raise ActivationError('Crontab changed during installation; review and retry.')
        attempted = True
        subprocess.run(['crontab', '-'], input=updated, text=True, check=True, timeout=20)
        if cron_read() != updated:
            raise ActivationError('Installed top 50 schedule did not match.')
    except BaseException:
        restore = True
        if attempted:
            try:
                current = cron_read()
                if current == updated:
                    subprocess.run(['crontab', '-'], input=original_cron, text=True, check=True, timeout=20)
                elif current != original_cron:
                    restore = False
            except Exception:
                restore = False
        if restore:
            for path in reversed(changed):
                if original[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, *original[path])
        else:
            print('External crontab changes detected; installed files retained. Review the backup.', file=sys.stderr)
        raise
    print(f'Daily top 50 schedule confirmed: {hour:02}:{minute:02} Europe/Istanbul')
    print(f'Next scheduled post: {next_run:%Y-%m-%d %H:%M} Istanbul')
    print('Posting: one five-slide carousel daily, with 50 fresh market prices.')
    print('Activation complete.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
