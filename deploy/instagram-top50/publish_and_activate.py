#!/usr/bin/env python3
"""Publish the approved top 50 carousel once, then activate its daily schedule."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

FILES = ('instagram_top50_prices.py', 'crypto_top50_data.py', 'instagram_top50_renderer.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True, help='Exact approved 40-character Git commit')
    parser.add_argument('--at', default='16:00', help='Daily Istanbul time, default 16:00')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise RuntimeError('Run on Selenium as the existing publisher user, without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise RuntimeError('Supply the exact approved Git revision.')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', args.at):
        raise RuntimeError('Daily time must be HH:MM in Istanbul.')
    root = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True, timeout=20).strip()
    if head != args.revision:
        raise RuntimeError('Deployment checkout does not match the approved revision.')
    # Publish the same bytes that the activation helper will install from Git.
    paths = FILES + ('deploy/instagram-top50/activate_top50_cron.py',
                     'deploy/instagram-top50/NOTICE')
    for name in paths:
        expected = subprocess.check_output(['git', '-C', str(root), 'show',
                                            f'{args.revision}:{name}'], timeout=20)
        if (root / name).read_bytes() != expected:
            raise RuntimeError(f'Deployment file differs from the approved revision: {name}')
    if not os.environ.get('INSTAGRAM_USER_ID') or not os.environ.get('INSTAGRAM_ACCESS_TOKEN'):
        raise RuntimeError('Load the existing Instagram environment before deployment.')
    home = Path.home()
    output = Path('/var/www/peerexo.com/public/instagram-rates/top50')
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(home / 'kiani-instagram-venv/bin/python'), '-u',
                    str(root / FILES[0]), '--publisher-root',
                    str(home / 'kiani-instagram-publisher'), '--publish'], check=True)
    runtime_hash = hashlib.sha256(b'\0'.join(
        name.encode() + b'\0' + (root / name).read_bytes() for name in FILES)).hexdigest()
    db = home / '.local/state/kiani-instagram-top50/top50.sqlite3'
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = con.execute("SELECT media_id,manifest_json FROM top50_publications "
                           "WHERE status='published' ORDER BY started_at DESC")
        media_id = next((media for media, manifest in rows
                         if json.loads(manifest).get('top50_runtime_fingerprint') == runtime_hash), None)
    finally:
        con.close()
    if media_id is None or not re.fullmatch(r'\d+', str(media_id)):
        raise RuntimeError('No successful post from this revision was found; schedule not activated. '
                           'Share the output before retrying.')
    subprocess.run(['/usr/bin/python3', str(root / 'deploy/instagram-top50/activate_top50_cron.py'),
                    '--repo', str(args.repo.expanduser().resolve()), '--revision', args.revision,
                    '--approved-media-id', str(media_id), '--at', args.at], check=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Child publishers provide their own sanitized error messages.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'ERROR: {message}', file=sys.stderr)
        raise SystemExit(1)
