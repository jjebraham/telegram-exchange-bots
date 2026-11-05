#!/usr/bin/env python3
"""Verify and install the approved currency-board cover without publishing."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

OLD_SHA = '13e7d47dfaba6cee6594dba9dd4d9c67fb4dff3c621eff9a14bc07f7d2cb0d91'
FILES = ('instagram_carousel.py', 'test_fiat_board.py', 'deploy/instagram-rates/carousel-sample.json')
PROBE = r'''
import sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import instagram_daily_rates as app
import instagram_carousel as board
try:
    rates = app.fetch_customer_rates()
    sections = board.collect_sections()
    rows, stamp = board.currency_board(sections)
    board.assert_fresh_sections(sections)
    with tempfile.TemporaryDirectory(prefix='kiani-board-render-') as directory:
        paths, _ = board.render_carousel(app, rates, sections, datetime.now(timezone.utc), Path(directory), sample=True)
        assert len(paths) >= 6 and all(p.stat().st_size > 10000 for p in paths)
        board.assert_fresh_sections(sections)
    print('Verified live FX currencies:', len(rows), '| source time:', stamp.isoformat(), '| preview slides:', len(paths))
    print('Live preview marked as sample; no Meta request was made.')
except Exception as exc:
    print('Live board preflight stopped:', type(exc).__name__)
    if isinstance(exc, board.CarouselError):
        print(str(exc))
    sys.exit(1)
'''


def owned(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise RuntimeError('A required publisher file is missing or not owned by this user: ' + path.name)
    return path.read_bytes()


def atomic(path, content, mode):
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        raise RuntimeError('Run as the publisher user with the exact reviewed revision.')
    os.umask(0o077)
    home, repo = Path.home(), args.repo.resolve()
    root = home / 'kiani-instagram-publisher'
    target = root / 'instagram_carousel.py'
    launcher = home / 'publish-kiani-instagram-rates.sh'
    story = home / '.local/state/kiani-instagram-stories/config.json'
    state = home / '.local/state/kiani-instagram-rates'
    python = home / 'kiani-instagram-venv/bin/python'
    if not root.is_dir() or root.is_symlink() or not python.is_file() or not state.is_dir():
        raise RuntimeError('An existing rates publisher prerequisite is missing.')
    blobs = {}
    for name in FILES:
        spec = args.revision + ':' + name
        size = int(subprocess.check_output(['git', '-C', str(repo), 'cat-file', '-s', spec], timeout=20))
        if not 0 < size < 150000:
            raise RuntimeError('Pinned source size is invalid.')
        blobs[name] = subprocess.check_output(['git', '-C', str(repo), 'show', spec], timeout=20)
        if len(blobs[name]) != size:
            raise RuntimeError('Pinned source length mismatch.')
    for name in FILES[:2]:
        compile(blobs[name], name, 'exec')
    if hashlib.sha256(owned(target)).hexdigest() != OLD_SHA and owned(target) != blobs['instagram_carousel.py']:
        raise RuntimeError('Installed carousel differs from the confirmed release; nothing changed.')
    tracked = (launcher, story, root/'instagram_daily_rates.py', root/'instagram_calendar.py',
               root/'fonts/Vazirmatn-Regular.ttf', root/'fonts/Vazirmatn-Bold.ttf',
               root/'assets/instagram/icons.png', root/'assets/instagram/icons.json', root/'assets/instagram/kiani-logo.svg')
    before = {p: hashlib.sha256(owned(p)).hexdigest() for p in tracked}
    cron_before = subprocess.check_output(['crontab', '-l'], timeout=15)
    old = owned(target)
    lock_path = state/'feed.json.lock'
    if lock_path.is_symlink():
        raise RuntimeError('The feed lock is a symlink.')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('The rates publisher is running; retry after it finishes.') from None
        receipt = state/'feed.json.publication.json'
        if receipt.exists() and json.loads(owned(receipt)).get('status') != 'published':
            raise RuntimeError('An uncertain rates publication needs reconciliation before installation.')
        with tempfile.TemporaryDirectory(prefix='kiani-currency-board-', dir=home) as name:
            stage = Path(name)
            for file, content in blobs.items():
                path = stage/file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for path in tracked[4:]:
                relative = path.relative_to(root)
                dest = stage/relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(owned(path))
            env = dict(os.environ, PYTHONPATH=str(stage) + os.pathsep + str(root),
                       PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
            subprocess.run([str(python), '-B', str(stage/'test_fiat_board.py')], cwd=stage, env=env,
                           check=True, timeout=60)
            subprocess.run([str(python), '-B', '-c', PROBE], cwd=stage, env=env, check=True, timeout=240)
            if not args.install:
                print('Preview only; the existing publisher was not changed.')
                return 0
            if (owned(target) != old or subprocess.check_output(['crontab', '-l'], timeout=15) != cron_before or
                any(hashlib.sha256(owned(path)).hexdigest() != digest for path, digest in before.items())):
                raise RuntimeError('Publisher files or schedule changed during checks; nothing installed.')
            if old == blobs['instagram_carousel.py']:
                print('This exact currency-board revision is already installed.')
                return 0
            backup = Path(tempfile.mkdtemp(prefix='kiani-fiat-board-backup-', dir=home))
            atomic(backup/'instagram_carousel.py', old, 0o600)
            mode = target.stat().st_mode & 0o777
            try:
                atomic(target, blobs['instagram_carousel.py'], mode)
                if owned(target) != blobs['instagram_carousel.py']:
                    raise RuntimeError('Installed carousel verification failed.')
                if subprocess.check_output(['crontab', '-l'], timeout=15) != cron_before:
                    raise RuntimeError('The schedule changed during installation.')
            except BaseException:
                if target.exists() and owned(target) == blobs['instagram_carousel.py']:
                    atomic(target, old, mode)
                raise
            print('Backup:', backup)
            print('Currency-board cover installed:', args.revision)
            print('Existing schedule, customer quotes, rate sources, and remaining slides preserved.')
            print('A complete fresh 25-currency market board is required for publication.')
            print('The delayed Story uses the new first slide. No Instagram post was published.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Currency-board installation stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
