#!/usr/bin/env python3
"""Read-only production and Runpod readiness audit; never starts a Pod."""
import argparse
from datetime import datetime, timedelta
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import warnings
from zoneinfo import ZoneInfo

from runpod_audit import AuditError, get_json, safe_summary


def summarize_detail(pod):
    result = safe_summary(pod)
    mounts = pod.get('mounts') if isinstance(pod.get('mounts'), dict) else None
    persistent = mounts.get('persistent') if mounts else None
    size = persistent.get('size') if isinstance(persistent, dict) else None
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 1000000:
        size = None
    path = persistent.get('path') if isinstance(persistent, dict) else None
    ports = pod.get('ports') if isinstance(pod.get('ports'), list) else None
    env = pod.get('env') if isinstance(pod.get('env'), dict) else None
    image = pod.get('image')
    result.update({
        'mount_details_present': mounts is not None,
        'persistent_volume_gb': size,
        'persistent_at_workspace': path == '/workspace' if path is not None else None,
        'ssh_port_22_exposed': '22/tcp' in ports if ports is not None else None,
        'pod_ssh_public_key_configured': (
            bool(env.get('SSH_PUBLIC_KEY') or env.get('PUBLIC_KEY')) if env is not None else None),
        'official_pytorch_image': image.startswith('runpod/pytorch:') if isinstance(image, str) else None,
    })
    return result


def local_audit(home):
    config = home / '.config/kiani-instagram-manual-news/config.json'
    try:
        revision = json.loads(config.read_text()).get('installed_revision')
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
            revision = 'unknown'
        print('Active Reel runtime:', revision)
    except (OSError, ValueError, TypeError):
        print('Active Reel runtime: unavailable')
    print('\nReel schedule entries:')
    try:
        cron = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=8)
        if cron.returncode:
            print('  unavailable')
        else:
            for line in cron.stdout.splitlines():
                line = line.strip()
                if line.startswith('CRON_TZ=') and re.fullmatch(r'CRON_TZ=[A-Za-z_+/\-]+', line):
                    print(' ', line)
                elif line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 6:
                        match = re.search(r'\b(run-kiani-instagram-(?:trial-reels|direct-reels|reel-schedule))\.sh\b', parts[5])
                        if match:
                            print(' ', ' '.join(parts[:5]), match.group(1) + '.sh')
    except (OSError, subprocess.SubprocessError):
        print('  unavailable')
    db = home / '.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
    print('\nRecent scheduled Reel outcomes (Istanbul):')
    try:
        if db.is_symlink() or not db.is_file():
            raise OSError()
        with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as con:
            since = (datetime.now(ZoneInfo('Europe/Istanbul')).date() - timedelta(days=7)).isoformat()
            records = con.execute('''SELECT posted_day, slot, status FROM scheduled_runs
                WHERE posted_day >= ? ORDER BY posted_day DESC, slot''', (since,)).fetchall()
            byday = {}
            for day, slot, status in records:
                if isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                    item = byday.setdefault(day, {'published': 0, 'other': 0})
                    item['published' if status == 'published' else 'other'] += 1
            for day, counts in list(byday.items())[:8]:
                print(' ', day, '| published:', counts['published'], '| other:', counts['other'])
            if not byday:
                print('  none recorded')
    except (OSError, sqlite3.Error):
        print('  unavailable')
    voice_db = home / '.local/state/kiani-instagram-voice-review/voices.sqlite3'
    print('\nVoice review status:')
    try:
        if voice_db.is_symlink() or not voice_db.is_file():
            raise OSError()
        with sqlite3.connect(voice_db.resolve().as_uri() + '?mode=ro', uri=True) as con:
            for name, available, verified, score, approved, enabled in con.execute(
                'SELECT name, available, verified, score, approved, enabled FROM voices ORDER BY name'):
                if name in {'Sahar', 'Aylin', 'Shahram', 'Adrian'}:
                    print(' ', name, '| available:', bool(available), '| verified:', bool(verified),
                          '| score:', score if isinstance(score, (float, int)) else 'not recorded',
                          '| approved:', bool(approved), '| enabled:', bool(enabled))
    except (OSError, sqlite3.Error):
        print('  unavailable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pod', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', args.pod):
        raise AuditError('Invalid Pod ID.')
    local_audit(Path.home())
    key = os.environ.get('RUNPOD_API_KEY', '').strip()
    if not key:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('\nRunpod API key (hidden; Enter skips): ').strip()
    if not key:
        print('Runpod detail skipped.')
        return
    pod = get_json('/pods/' + args.pod, key)
    if pod.get('id') != args.pod:
        raise AuditError('Pod identity did not match the requested ID.')
    print('\nRead-only Pod details:')
    print(json.dumps(summarize_detail(pod), ensure_ascii=True))
    print('No Pod was started or stopped, and no Instagram request was made.')


if __name__ == '__main__':
    try:
        main()
    except (AuditError, getpass.GetPassWarning, EOFError) as exc:
        print('Read-only inspection stopped:', str(exc) if isinstance(exc, AuditError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
