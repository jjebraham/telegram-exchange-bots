#!/usr/bin/env python3
"""Extract the reviewed rates/gold repair without changing a repository checkout."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

GOLD_FILES = ('iran_gold_data.py', 'iran_gold_quorum.py', 'iran_gold_servix.py',
    'instagram_iran_gold.py', 'instagram_iran_gold_renderer.py', 'economic_calendar_data.py',
    'instagram_economic_calendar_renderer.py', 'tests/test_instagram_iran_gold.py',
    'tests/test_iran_gold_servix.py', 'tests/test_iran_gold_template.py',
    'deploy/instagram-iran-gold/activate_servix.py', 'deploy/instagram-iran-gold/activate_template.py',
    'global_metals_data.py', 'instagram_global_metals_renderer.py',
    'deploy/instagram-iran-gold/activate_metals.py', 'assets/instagram/gold-coin.png',
    'assets/instagram/gold-bars.png', 'iran_gold_tgju.py')
FILES = GOLD_FILES + ('instagram_daily_rates.py', 'instagram_carousel.py',
    'deploy/instagram-price-recovery/run_recovery.py',
    'deploy/instagram-price-recovery/activate_recovery.py', 'deploy/instagram-price-recovery/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home()/'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--target', choices=('both', 'rates', 'gold'), default='both')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Use the exact reviewed revision as the existing publisher user, without sudo.')
    os.umask(0o077)
    root = Path.home()/'.local/state/kiani-instagram-price-recovery/source'/args.revision
    total = 0
    for name in FILES:
        spec = args.revision+':'+name
        size = int(subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', '-s', spec], timeout=20))
        total += size
        if size <= 0 or total > 768*1024:
            raise RuntimeError('Pinned repair source exceeds its size limit.')
        data = subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', 'blob', spec], timeout=20)
        if len(data) != size:
            raise RuntimeError('Pinned source size differs.')
        target = root/name
        if target.is_symlink() or target.exists() and target.read_bytes() != data:
            raise RuntimeError('An existing pinned repair file differs.')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.exists():
            target.write_bytes(data)
    print(f'Extracted/verified {len(FILES)} files ({total/1024:.1f} KiB); no checkout.', flush=True)
    helper = root/'deploy/instagram-price-recovery/activate_recovery.py'
    python = Path.home()/'kiani-instagram-venv/bin/python'
    command = [str(python), '-u', str(helper), '--runtime', str(root), '--repo', str(args.repo),
               '--revision', args.revision, '--target', args.target]
    if args.activate:
        command.append('--activate')
    # Load the existing private configuration only inside the child. No token,
    # API key, environment dump or shell trace is printed or written here.
    shell = 'set -e; set -a; . "$HOME/.kiani-instagram.env"; set +a; exec "$@"'
    completed = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', shell, 'repair', *command],
        cwd=root, env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'))
    return completed.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Repair launcher stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
