#!/usr/bin/env python3
"""Install the reviewed exchange-row parser fix without changing Feed schedules."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ORIGINAL = '821cba7ddd0a7361e98c048623ddf05fca672837'
FILE = 'instagram_carousel.py'


class ActivationError(RuntimeError):
    pass


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def check_live(root):
    """Read current assessed data and show which quotes pass the installed parser."""
    spec = importlib.util.spec_from_file_location('usdt_comparison_check', root / FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    repo = Path(os.environ.get('INSTAGRAM_TELEGRAM_REPO', str(Path.home() / 'telegram_bot_repo')))
    text = module._export(repo, 'alanchande-usdt-exchanges')
    section = module._parse_usdt(text)
    print(json.dumps(section, ensure_ascii=False, indent=2))
    print('Live exchange comparison verified. Nothing published.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', help='Exact reviewed Git commit SHA')
    parser.add_argument('--check-live', action='store_true', help='Read-only current exchange-table check; run in the existing venv with its environment loaded')
    args = parser.parse_args()
    home = Path.home().resolve()
    root = home / 'kiani-instagram-publisher'
    if args.check_live:
        check_live(root)
        return 0
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise ActivationError('Run as the existing publisher user, without sudo')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision or ''):
        raise ActivationError('Supply the exact reviewed revision')
    target = root / FILE
    if root.is_symlink() or target.is_symlink() or not target.is_file():
        raise ActivationError('The installed carousel module could not be safely located')
    if target.stat().st_uid != os.geteuid():
        raise ActivationError('Run as the installed publisher owner')
    repo = args.repo.expanduser().resolve()
    wanted = subprocess.check_output(['git', '-C', str(repo), 'show', f'{args.revision}:{FILE}'], timeout=20)
    previous = target.read_bytes()
    original = subprocess.check_output(['git', '-C', str(repo), 'show', f'{ORIGINAL}:{FILE}'], timeout=20)
    if previous not in (original, wanted):
        raise ActivationError('Installed carousel code differs from the reviewed versions; nothing changed')
    compile(wanted, FILE, 'exec')
    cron = subprocess.check_output(['crontab', '-l'], text=True, timeout=15)
    jobs = [line.split() for line in cron.splitlines()
            if 'publish-kiani-instagram-rates.sh' in line and not line.lstrip().startswith('#')]
    if len(jobs) != 1 or jobs[0][:5] != ['30', '8', '*', '*', '*']:
        raise ActivationError('The confirmed daily rates job could not be located')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            names = {Path(arg.decode(errors='replace')).name for arg in (proc / 'cmdline').read_bytes().split(b'\0') if arg}
            if names & {'publish-kiani-instagram-rates.sh', 'instagram_daily_rates.py'}:
                raise ActivationError('The rates publisher is running; retry after it finishes')
        except (OSError, ValueError):
            continue
    backup = Path(tempfile.mkdtemp(prefix='kiani-instagram-usdt-fix-backup-', dir=home))
    backup.chmod(0o700)
    saved = backup / FILE
    saved.write_bytes(previous)
    saved.chmod(0o600)
    try:
        if target.read_bytes() != previous:
            raise ActivationError('Carousel code changed during preparation')
        atomic_write(target, wanted)
        if target.read_bytes() != wanted:
            raise ActivationError('The installed carousel fix could not be confirmed')
        if subprocess.check_output(['crontab', '-l'], text=True, timeout=15) != cron:
            raise ActivationError('Crontab changed during installation')
    except BaseException:
        if target.read_bytes() == wanted:
            atomic_write(target, previous)
        raise
    print(f'Backup: {backup}')
    print(f'Installed USDT comparison fix: {args.revision}')
    print(f'Carousel module SHA256: {hashlib.sha256(wanted).hexdigest()}')
    print('Comparison keeps valid exchanges; individual invalid quotes are logged and excluded.')
    print('At least two valid quotes and a fresh assessed export are still required.')
    print('Daily rates Feed remains 11:30 Istanbul; Story preview follows 30 minutes later.')
    print('Activation complete. No Instagram post was published during installation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: USDT comparison fix could not finish ({type(exc).__name__}).', file=sys.stderr)
        if isinstance(exc, ActivationError) or type(exc).__name__ == 'CarouselError':
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
