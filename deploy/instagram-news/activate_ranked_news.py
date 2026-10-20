#!/usr/bin/env python3
"""Activate reviewed two-per-category news jobs while retaining existing state."""
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
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

HASHES = {
    'kiani-instagram-news-publisher/instagram_crypto_news.py': 'e4e7de231022170cceece1e7ad0eb1d7be6eb59e423ad0b60caeb7cd9c243063',
    'kiani-instagram-economy-publisher/instagram_economy_news.py': '9aa970977036c2ed39e21f96e6ba1c87ec8dcf36a199ed59807e50a99c3978c7',
    'kiani-instagram-economy-publisher/economy_news_picker.py': '1624ab9f37fd052b9c0c43e7ff3bc12c72197e31bdd7d6a7e8171edf36dbfe24',
}
BEGIN, END = '# BEGIN Kiani ranked news v2', '# END Kiani ranked news v2'


def atomic(path, data, mode):
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink installation path.')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cron_read():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def wrappers(home, runtime):
    python = shlex.quote(str(home / 'kiani-instagram-venv/bin/python'))
    app = shlex.quote(str(runtime / 'instagram_ranked_news.py'))
    header = '''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 077
'''
    outputs = {}
    for kind, filename in (('crypto', 'publish-kiani-instagram-news.sh'), ('economy', 'publish-kiani-instagram-economy.sh')):
        text = header + 'action="${1:-first}"\ncase "$action" in\n'
        if kind == 'economy':
            text += f'  collect) exec {python} -u {app} --kind economy --collect-only ;;\n'
        text += '''  first|publish) slot=first ;;
  second) slot=second ;;
  *) echo "Usage: first|second''' + ('|collect' if kind == 'economy' else '') + '''" >&2; exit 2 ;;
esac
set -a
. "$HOME/.kiani-instagram.env"
set +a
'''
        text += f'exec {python} -u {app} --kind {kind} --slot "$slot" --publish\n'
        outputs[home / filename] = text.encode()
    return outputs


def new_cron(original, home):
    kept, counts = [], {'crypto_first': 0, 'crypto_second': 0, 'economy_first': 0, 'economy_second': 0, 'collect': 0}
    paths = {str(home / 'publish-kiani-instagram-news.sh'): 'crypto',
             str(home / 'publish-kiani-instagram-economy.sh'): 'economy'}
    for line in original.decode().splitlines():
        stripped = line.strip()
        if stripped in (BEGIN, END):
            continue
        if stripped.startswith('CRON_TZ=') and stripped.split('=', 1)[1].strip('"\'') not in {'UTC', 'Etc/UTC'}:
            raise RuntimeError('A non-UTC CRON_TZ needs review before changing schedules.')
        if not stripped or stripped.startswith('#') or not any(path in line for path in paths):
            kept.append(line)
            continue
        fields = stripped.split(None, 5)
        if len(fields) != 6:
            raise RuntimeError('An existing news cron command has an unexpected format.')
        schedule, command = ' '.join(fields[:5]), shlex.split(fields[5])
        if not command or command[0] not in paths:
            raise RuntimeError('An indirect news cron command needs review.')
        kind = paths[command[0]]
        action = command[1] if len(command) > 1 and command[1] not in {'>>', '>'} else 'first'
        if action == 'publish':
            action = 'first'
        key = 'collect' if action == 'collect' else kind + '_' + action
        expected = {'crypto_first': '0 15 * * *', 'crypto_second': '30 18 * * *',
                    'economy_first': '0 10 * * *', 'economy_second': '0 17 * * *', 'collect': '30 * * * *'}
        tail = command[2:] if len(command) > 1 and command[1] not in {'>>', '>'} else command[1:]
        logname = 'kiani-instagram-news-cron.log' if kind == 'crypto' else 'kiani-instagram-economy-cron.log'
        if key not in expected or schedule != expected[key] or tail != ['>>', str(home / logname), '2>&1']:
            raise RuntimeError('An existing news cron schedule/argument differs; nothing replaced.')
        counts[key] += 1
    if any(counts[k] != 1 for k in ('crypto_first', 'economy_first', 'collect')) or any(v > 1 for v in counts.values()):
        raise RuntimeError('Expected exactly one primary news job per category and one collection job.')
    crypto, economy = home / 'publish-kiani-instagram-news.sh', home / 'publish-kiani-instagram-economy.sh'
    block = [BEGIN,
        f'30 * * * * {economy} collect >> {home}/kiani-instagram-economy-cron.log 2>&1',
        f'0 10 * * * {economy} first >> {home}/kiani-instagram-economy-cron.log 2>&1',
        f'0 17 * * * {economy} second >> {home}/kiani-instagram-economy-cron.log 2>&1',
        f'0 15 * * * {crypto} first >> {home}/kiani-instagram-news-cron.log 2>&1',
        f'30 18 * * * {crypto} second >> {home}/kiani-instagram-news-cron.log 2>&1', END]
    return ('\n'.join(kept).rstrip() + '\n\n' + '\n'.join(block) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing publisher user without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Supply the reviewed revision.')
    home, runtime = Path.home(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    import instagram_ranked_news as app
    fingerprint = app.runtime_fingerprint(runtime)
    verified = {}
    now = time.time()
    for kind in ('crypto', 'economy'):
        for path in sorted((app.STATE / 'runs').glob(kind + '-*/ranking.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(path.read_text())
            if (data.get('status') == 'previewed' and data.get('runtime_fingerprint') == fingerprint
                and now - 48 * 3600 <= data.get('selected_at', 0) <= now
                and len(data.get('chosen_ids', [])) == 2 and len(data.get('preview_urls', [])) >= 2):
                verified[kind] = str(path)
                break
    if len(verified) != 2:
        raise RuntimeError('First run and review a current two-story preview for BOTH categories from this exact runtime.')
    zone = subprocess.check_output(['timedatectl', 'show', '--property=Timezone', '--value'], text=True, timeout=15).strip()
    if zone not in {'UTC', 'Etc/UTC'} or datetime.now(ZoneInfo('Europe/Istanbul')).utcoffset() != timedelta(hours=3):
        raise RuntimeError('Timezone differs from the verified UTC/Istanbul schedules; nothing changed.')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron'], timeout=15).returncode:
        raise RuntimeError('The cron service is not active.')
    for relative, expected in HASHES.items():
        path = home / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Installed legacy publisher differs from the audited revision; review before handover.')
    for name in ('.kiani-instagram.env',):
        path = home / name
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            raise RuntimeError('The existing private publisher configuration is missing or has an unexpected owner.')
    release = home / 'kiani-instagram-ranked-news-releases' / args.revision
    release.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in (*app.RUNTIME_FILES, 'selector_trial_runtime/PINNED.md'):
        destination = release / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = (runtime / name).read_bytes()
        if destination.is_symlink() or destination.exists() and destination.read_bytes() != data:
            raise RuntimeError('An existing versioned runtime differs; no overwrite performed.')
        if not destination.exists():
            atomic(destination, data, 0o600)
    proposed = wrappers(home, release)
    old_wrappers = {}
    for path in proposed:
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            raise RuntimeError('An expected publisher launcher is missing or has an unexpected owner.')
        old_wrappers[path] = (path.read_bytes(), path.stat().st_mode & 0o777)
    paths = [app.STATE / 'selection.lock', Path(str(app.SOURCES['crypto']) + '.lock'),
             app.SOURCES['crypto'].parent / 'publisher.lock', Path(str(app.SOURCES['economy']) + '.lock')]
    with ExitStack() as stack:
        for path in sorted(paths):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A current news publisher is busy; retry activation after it finishes.') from None
        if any(path.read_bytes() != data for path, (data, _) in old_wrappers.items()):
            raise RuntimeError('A news launcher changed during preparation; nothing replaced.')
        original = cron_read()
        replacement = new_cron(original, home)
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-ranked-news-backup-', dir=home))
        (backup / 'crontab.txt').write_bytes(original)
        for path, (data, mode) in old_wrappers.items():
            (backup / path.name).write_bytes(data)
        installed = False
        try:
            if cron_read() != original:
                raise RuntimeError('The crontab changed during preparation; retry after review.')
            for path, data in proposed.items():
                atomic(path, data, 0o700)
            if cron_read() != original:
                raise RuntimeError('The crontab changed during activation; launchers will be restored.')
            subprocess.run(['crontab', '-'], input=replacement, check=True, capture_output=True, timeout=15)
            installed = True
            if cron_read() != replacement:
                raise RuntimeError('The installed crontab did not match the prepared schedule.')
            atomic(app.STATE / 'activation.json', json.dumps(dict(revision=args.revision,
                fingerprint=fingerprint, activated_at=time.time(), previews=verified, backup=str(backup)), indent=2).encode(), 0o600)
        except BaseException:
            for path, (data, mode) in old_wrappers.items():
                current = path.read_bytes()
                if current == proposed[path]:
                    atomic(path, data, mode)
                elif current != data:
                    print('Concurrent launcher change retained:', path, file=sys.stderr)
            if installed and cron_read() == replacement:
                subprocess.run(['crontab', '-'], input=original, check=True, capture_output=True, timeout=15)
            print('Activation did not complete. Backup:', backup, file=sys.stderr)
            raise
    print('Backup:', backup)
    print('Economy Feed: 13:00 and 20:00 Europe/Istanbul. Crypto Feed: 18:00 and 21:30.')
    print('Two distinct qualifying stories per category/day maximum; each slot ranks the rolling last 24 hours.')
    print('Original news databases preserved. Rates, top 50 and delayed Story jobs preserved.')
    print('Stories follow each successful Feed post 30 minutes later through the existing worker.')
    print('Activation complete. No immediate Instagram post was published.')
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else f'Activation failed ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)
