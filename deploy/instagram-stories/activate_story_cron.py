#!/usr/bin/env python3
"""Install delayed Story previews for the four existing daily Feed publishers."""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile

FILES = ('instagram_delayed_stories.py', 'instagram_story_renderer.py')
SHARED = ('instagram_daily_rates.py', 'fonts/Vazirmatn-Regular.ttf',
          'fonts/Vazirmatn-Bold.ttf', 'assets/instagram/kiani-logo.svg')
BEGIN = '# BEGIN Kiani delayed Instagram Stories'
END = '# END Kiani delayed Instagram Stories'
WRAPPER = '''#!/bin/bash
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
export TZ=Europe/Istanbul
export PYTHONIOENCODING=utf-8
umask 077
set -a
. "$HOME/.kiani-instagram.env"
set +a
"$HOME/kiani-instagram-venv/bin/python" -u \\
  "$HOME/kiani-instagram-story-publisher/instagram_delayed_stories.py" \\
  --config "$HOME/.local/state/kiani-instagram-stories/config.json" --run
'''


class ActivationError(RuntimeError):
    pass


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return subprocess.check_output(['crontab', '-l'], text=True, timeout=15)


def cron_base(cron):
    lines, inside, count = [], False, 0
    for line in cron.splitlines(keepends=True):
        if line.strip() == BEGIN:
            if inside or count:
                raise ActivationError('Duplicate Story cron block')
            inside, count = True, count + 1
        elif line.strip() == END:
            if not inside:
                raise ActivationError('Story cron end has no beginning')
            inside = False
        elif not inside:
            if 'publish-kiani-instagram-stories.sh' in line and not line.lstrip().startswith('#'):
                raise ActivationError('An unmanaged Story job needs review')
            lines.append(line)
    if inside:
        raise ActivationError('Story cron block is incomplete')
    return ''.join(lines).rstrip() + '\n'


def rates_settings(text, home):
    """Change only the known two-mode loop; never rewrite the rates launcher."""
    loop = re.compile(r'(?m)^(\s*for\s+mode\s+in\s+)(feed\s+story|story\s+feed)(\s*;\s*do\s*)$')
    matches = list(loop.finditer(text))
    if len(matches) == 1:
        edited = loop.sub(lambda m: m[1] + 'feed' + m[3], text)
    elif re.search(r'(?m)^\s*for\s+mode\s+in\s+feed\s*;\s*do\s*$', text):
        edited = text  # Idempotent upgrade of an already-activated launcher.
    else:
        raise ActivationError('Rates launcher modes differ from the reviewed loop; nothing changed')
    if 'SCRIPT="$HOME/kiani-instagram-publisher/instagram_daily_rates.py"' not in text:
        raise ActivationError('Rates publisher path differs from the reviewed launcher')
    if 'INSTAGRAM_STATE_FILE="$STATE_DIR/$mode.json"' not in text:
        raise ActivationError('Rates launcher does not retain separate Feed state')
    assignments = re.findall(r'(?m)^STATE_DIR=(.+)$', text)
    if len(assignments) != 1:
        raise ActivationError('Could not resolve the existing rates state directory')
    words = shlex.split(assignments[0])
    if len(words) != 1:
        raise ActivationError('Unexpected rates state directory expression')
    directory = words[0].replace('${HOME}', str(home)).replace('$HOME', str(home))
    if '$' in directory or '`' in directory:
        raise ActivationError('Rates state directory requires manual review')
    state = (Path(directory) / 'feed.json').resolve()
    if not state.is_relative_to(home) or not state.is_file():
        raise ActivationError('The existing rates Feed state could not be located')
    return edited, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True, help='Exact reviewed Git commit SHA')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise ActivationError('Run as the existing Instagram publisher user, without sudo')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise ActivationError('Supply an exact 40-character reviewed Git revision')
    home, repo = Path.home().resolve(), args.repo.expanduser().resolve()
    clock = dict(os.environ)
    clock.pop('TZ', None)
    if subprocess.check_output(['date', '+%z'], text=True, env=clock).strip() != '+0000':
        raise ActivationError('This setup expects the confirmed UTC cron server')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'cron']).returncode:
        raise ActivationError('The cron service is not active')
    env, rates = home / '.kiani-instagram.env', home / 'publish-kiani-instagram-rates.sh'
    python = home / 'kiani-instagram-venv/bin/python'
    root = home / 'kiani-instagram-publisher'
    for path in (env, rates, python, root / 'instagram_daily_rates.py'):
        if not path.is_file() or (path != python and path.is_symlink()):
            raise ActivationError('An existing publisher prerequisite is missing')
    if env.stat().st_uid != os.geteuid():
        raise ActivationError('Run as the private Instagram environment owner')
    old_rates = rates.read_bytes()
    new_rates, feed_state = rates_settings(old_rates.decode('utf-8'), home)
    new_rates = new_rates.encode('utf-8')
    old_cron = cron_read()
    base = cron_base(old_cron)
    expected_jobs = {
        'rates': ('30', '8'), 'economy': ('0', '10'),
        'top50': ('0', '13'), 'news': ('0', '15'),
    }
    for kind, expected in expected_jobs.items():
        name = f'publish-kiani-instagram-{kind}.sh'
        jobs = [line.split() for line in base.splitlines() if name in line and not line.lstrip().startswith('#')]
        # Economy also has an hourly collection command. Select its publish job.
        jobs = [job for job in jobs if 'publish' in job[6:] or kind == 'news']
        if len(jobs) != 1 or tuple(jobs[0][:2]) != expected or jobs[0][2:5] != ['*', '*', '*']:
            raise ActivationError(f'Existing {kind} Feed schedule differs from the approved daily schedule')
    contents = {name: subprocess.check_output(['git', '-C', str(repo), 'show', f'{args.revision}:{name}']) for name in FILES}
    for name in SHARED:
        reviewed = subprocess.check_output(['git', '-C', str(repo), 'show', f'{args.revision}:{name}'])
        if (root / name).read_bytes() != reviewed:
            raise ActivationError('Installed shared Instagram assets differ from the reviewed assets')
    sources = {
        'rates': str(feed_state),
        'economy': str(home / '.local/state/kiani-instagram-economy/economy.sqlite3'),
        'top50': str(home / '.local/state/kiani-instagram-top50/top50.sqlite3'),
        'crypto': str(home / '.local/state/kiani-instagram-news/news.sqlite3'),
    }
    for kind, value in sources.items():
        if not Path(value).is_file():
            raise ActivationError(f'The existing {kind} publication state is missing')
    public = Path('/var/www/peerexo.com/public/instagram-rates')
    public.joinpath('stories').mkdir(exist_ok=True, mode=0o755)
    public.joinpath('stories').chmod(0o755)
    state_dir = home / '.local/state/kiani-instagram-stories'
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    config_path, db_path = state_dir / 'config.json', state_dir / 'stories.sqlite3'
    config = dict(db=str(db_path), sources=sources, publisher_root=str(root),
                  public_root=str(public), public_base='https://peerexo.com/instagram-rates')
    installed = home / 'kiani-instagram-story-publisher'
    launcher = home / 'publish-kiani-instagram-stories.sh'
    log = home / 'kiani-instagram-stories-cron.log'
    command = '* * * * * ' + shlex.quote(str(launcher)) + ' >> ' + shlex.quote(str(log)) + ' 2>&1\n'
    new_cron = base + BEGIN + '\n' + command + END + '\n'
    changed = {installed / name: (data, 0o644) for name, data in contents.items()}
    changed.update({config_path: (json.dumps(config, indent=2).encode() + b'\n', 0o600),
                    launcher: (WRAPPER.encode(), 0o700), rates: (new_rates, rates.stat().st_mode & 0o777)})
    for path in changed:
        if path.is_symlink():
            raise ActivationError('Deployment refuses to replace symlinks')
    with db_path.with_suffix('.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ActivationError('A Story worker is running; retry shortly') from None
        backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-stories-backup-', dir=home))
        backup.chmod(0o700)
        before = {path: (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None for path in changed}
        for index, (path, previous) in enumerate(before.items()):
            if previous:
                atomic_write(backup / f'file-{index}', previous[0], 0o600)
        atomic_write(backup / 'crontab.txt', old_cron.encode(), 0o600)
        atomic_write(backup / 'paths.json', json.dumps([str(path) for path in changed]).encode(), 0o600)
        if db_path.exists():
            original = sqlite3.connect(db_path)
            saved = sqlite3.connect(backup / 'stories.sqlite3')
            try:
                original.backup(saved)
            finally:
                original.close()
                saved.close()
        cron_attempted = False
        try:
            if rates.read_bytes() != old_rates or cron_read() != old_cron:
                raise ActivationError('Publisher configuration changed during preparation')
            for path, (data, mode) in changed.items():
                atomic_write(path, data, mode)
            subprocess.run(['bash', '-n', str(rates)], check=True)
            subprocess.run(['bash', '-n', str(launcher)], check=True)
            subprocess.run([str(python), '-c',
                            'import arabic_reshaper; from bidi.algorithm import get_display; from PIL import Image, ImageFont'], check=True)
            spec = importlib.util.spec_from_file_location('story_queue_setup', installed / FILES[0])
            worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(worker)
            con = worker.database(db_path)
            try:
                worker.initialize(con, config)
                if len({kind for _, kind, _ in worker.published_records(config, 0)}) != 4:
                    raise ActivationError('One of the existing publication manifests could not be read')
            finally:
                con.close()
            if cron_read() != old_cron:
                raise ActivationError('Crontab changed during installation')
            cron_attempted = True
            subprocess.run(['crontab', '-'], input=new_cron, text=True, check=True, timeout=15)
            if cron_read() != new_cron:
                raise ActivationError('The installed Story schedule could not be confirmed')
        except Exception:
            if cron_attempted:
                current = cron_read()
                if current == new_cron:
                    subprocess.run(['crontab', '-'], input=old_cron, text=True, check=True, timeout=15)
                elif current != old_cron:
                    print(f'External cron changes detected; installed files retained. Backup: {backup}', file=sys.stderr)
                    raise
            for path, previous in before.items():
                if previous:
                    atomic_write(path, previous[0], previous[1])
                elif path.exists():
                    path.unlink()
            raise
    print(f'Backup: {backup}')
    print(f'Installed Story worker revision: {args.revision}')
    print('Existing rates, economy, top 50 and crypto Feed times preserved.')
    print('Rates immediate Story removed; all four posts now use the delayed queue.')
    print('Stories: first slide of each successful Feed post, 30 minutes later.')
    print('Typical Istanbul Story times: 12:00, 13:30, 16:30, 18:30 (worker checks each minute).')
    print('Existing posts baselined; no historical Stories published during setup.')
    print(f'Story log: {log}')
    print('Activation complete.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: Story activation failed ({type(exc).__name__}).', file=sys.stderr)
        if isinstance(exc, ActivationError):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
