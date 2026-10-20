#!/usr/bin/env python3
"""Extract the small daily gold runtime from a pinned Git revision, without checkout."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = ('iran_gold_data.py', 'instagram_iran_gold.py', 'instagram_iran_gold_renderer.py',
         'economic_calendar_data.py', 'instagram_economic_calendar_renderer.py',
         'tests/test_instagram_iran_gold.py', 'instagram_delayed_stories.py',
         'instagram_story_renderer.py', 'deploy/instagram-iran-gold/activate_gold.py',
         'deploy/instagram-iran-gold/run_gold.py', 'deploy/instagram-iran-gold/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the existing publisher user without sudo and supply the reviewed revision.')
    os.umask(0o077)
    home, sources, total = Path.home(), {}, 0
    for p in (home, Path('/var/www/peerexo.com/public/instagram-rates')):
        if not p.is_dir() or shutil.disk_usage(p).free < 128 * 1024**2:
            raise RuntimeError('At least 128 MiB free is required for gold data and images.')
    for name in FILES:
        spec = args.revision + ':' + name
        size = int(subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', '-s', spec], timeout=20))
        total += size
        if size <= 0 or total > 512 * 1024:
            raise RuntimeError('Pinned source extraction exceeded its limit.')
        data = subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', 'blob', spec], timeout=20)
        if len(data) != size:
            raise RuntimeError('Pinned source blob size mismatch.')
        sources[name] = data
    root = home / '.local/state/kiani-instagram-iran-gold/source' / args.revision
    for name, data in sources.items():
        p = root / name
        if p.is_symlink() or p.exists() and p.read_bytes() != data:
            raise RuntimeError('An existing pinned gold source differs.')
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not p.exists():
            p.write_bytes(data)
    python = home / 'kiani-instagram-venv/bin/python'
    command = [str(python), '-u', str(root / 'deploy/instagram-iran-gold/activate_gold.py'),
               '--runtime', str(root), '--revision', args.revision] if args.activate else [str(python), '-u', str(root / 'instagram_iran_gold.py')]
    print(f'Extracted/verified {len(FILES)} files ({total / 1024:.1f} KiB); no repository checkout.', flush=True)
    print('Activating guarded daily gold publisher.' if args.activate else 'Source preflight: fresh TGJU/DolarChand collection; unsafe data is blocked. No Meta API contact.', flush=True)
    return subprocess.run(command, cwd=root, env=dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Asia/Tehran')).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        raise SystemExit(1)
