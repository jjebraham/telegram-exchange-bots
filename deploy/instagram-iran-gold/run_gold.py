#!/usr/bin/env python3
"""Pinned small-runtime Servix upgrade, live preview, and explicit one-time post."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = ('iran_gold_data.py', 'iran_gold_quorum.py', 'iran_gold_servix.py', 'instagram_iran_gold.py',
         'instagram_iran_gold_renderer.py', 'economic_calendar_data.py', 'instagram_economic_calendar_renderer.py',
         'tests/test_instagram_iran_gold.py', 'tests/test_iran_gold_servix.py',
         'deploy/instagram-iran-gold/activate_servix.py', 'deploy/instagram-iran-gold/run_gold.py',
         'deploy/instagram-iran-gold/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--setup-servix', action='store_true')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--publish-now-on', metavar='YYYY-MM-DD')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the existing publisher user without sudo and supply the reviewed revision.')
    if args.publish_now_on:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if args.publish_now_on != datetime.now(ZoneInfo('Asia/Tehran')).date().isoformat():
            parser.error('One-time posting must specify the current Tehran day explicitly.')
    os.umask(0o077)
    home, sources, total = Path.home(), {}, 0
    for path in (home, Path('/var/www/peerexo.com/public/instagram-rates')):
        if not path.is_dir() or shutil.disk_usage(path).free < 128 * 1024**2:
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
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned gold source differs.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            path.write_bytes(data)
    python = home / 'kiani-instagram-venv/bin/python'
    app = [str(python), '-u', str(root / 'instagram_iran_gold.py')]
    admin = [str(python), '-u', str(root / 'deploy/instagram-iran-gold/activate_servix.py'),
             '--runtime', str(root), '--revision', args.revision]
    env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Asia/Tehran')
    def run(command):
        subprocess.run(command, cwd=root, env=env, check=True)
    print(f'Extracted/verified {len(FILES)} files ({total / 1024:.1f} KiB); no repository checkout.', flush=True)
    print('Running offline synthetic checks; these do not publish or call price APIs.', flush=True)
    run(app + ['--self-check'])
    if args.setup_servix:
        run(admin + ['--configure-key'])
    print('Live verified preview with Servix corroboration required. No Meta API contact.', flush=True)
    run(app + ['--require-servix'])
    if args.activate:
        run(admin)
    if args.publish_now_on:
        run(admin + ['--post-on', args.publish_now_on])
    else:
        print('No one-time post requested; no Instagram content published by this command.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        raise SystemExit(1)

