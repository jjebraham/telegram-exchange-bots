#!/usr/bin/env python3
"""Preview or activate the small pinned top-50-plus-gainers runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

RUNTIME = ('instagram_top50_prices.py', 'crypto_top50_data.py', 'instagram_top50_renderer.py')
FILES = RUNTIME + ('deploy/instagram-top50/upgrade_gainers.py',
    'deploy/instagram-top50/run_gainers.py', 'deploy/instagram-top50/activate_top50_cron.py',
    'deploy/instagram-top50/NOTICE', 'deploy/instagram-top50/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('Run as the publisher user, without sudo, using the reviewed revision.')
    os.umask(0o022)
    home = Path.home()
    public = Path('/var/www/peerexo.com/public/instagram-rates')
    for path in (home, public):
        if not path.is_dir() or shutil.disk_usage(path).free < 128 * 1024**2:
            raise RuntimeError('At least 128 MiB free is required for the source preview.')
    sources, total = {}, 0
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
    root = home / '.local/state/kiani-instagram-top50/source' / args.revision
    for name, data in sources.items():
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned source differs.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    python = home / 'kiani-instagram-venv/bin/python'
    output = public / 'top50-gainers-preview'
    if args.activate:
        command = [str(python), '-u', str(root / 'deploy/instagram-top50/upgrade_gainers.py'),
                   '--runtime', str(root), '--revision', args.revision]
    else:
        command = [str(python), '-u', str(root / 'instagram_top50_prices.py'),
                   '--publisher-root', str(home / 'kiani-instagram-publisher'), '--output', str(output)]
    print(f'Extracted/verified {len(FILES)} files ({total/1024:.1f} KiB); no repository checkout.', flush=True)
    print('Activating the gainers cover.' if args.activate else
          'Preview only: 24-hour gainers from the top 100, followed by 50 prices. No Meta API contact.', flush=True)
    result = subprocess.run(command, cwd=root, env=dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul'))
    if result.returncode or args.activate:
        return result.returncode
    digest = hashlib.sha256(b'\0'.join(name.encode() + b'\0' + sources[name] for name in RUNTIME)).hexdigest()
    db = home / '.local/state/kiani-instagram-top50/top50.sqlite3'
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        for raw, in con.execute('SELECT manifest_json FROM top50_snapshots ORDER BY created_at DESC LIMIT 20'):
            manifest = json.loads(raw)
            if manifest.get('top50_runtime_fingerprint') == digest and not manifest.get('sample'):
                for path in manifest['images']:
                    print('Preview slide:', 'https://peerexo.com/instagram-rates/top50-gainers-preview/' + Path(path).name)
                break
    finally:
        con.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
