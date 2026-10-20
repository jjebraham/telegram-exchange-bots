#!/usr/bin/env python3
"""Extract only the ranked-news runtime, then preview or activate reviewed jobs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = (
    'instagram_ranked_news.py', 'crypto_news_trial.py',
    'selector_trial_runtime/economy_news_picker.py',
    'selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py',
    'selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md',
    'deploy/instagram-news/activate_ranked_news.py',
    'deploy/instagram-news/RANKED-NEWS.md',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--kind', choices=('both', 'crypto', 'economy'), default='both')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the publisher user without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Supply the exact reviewed revision.')
    os.umask(0o077)
    home = Path.home()
    for path in (home, Path('/var/www/peerexo.com/public/instagram-rates')):
        if not path.is_dir() or shutil.disk_usage(path).free < 256 * 1024**2:
            raise RuntimeError('At least 256 MiB free is required for previews and safe state writes.')
    repo = args.repo.expanduser().resolve()
    sources, size = {}, 0
    for name in FILES:
        spec = args.revision + ':' + name
        length = int(subprocess.check_output(['git', '-C', str(repo), 'cat-file', '-s', spec], timeout=20))
        size += length
        if length <= 0 or size > 2 * 1024**2:
            raise RuntimeError('Source extraction exceeded its limit.')
        sources[name] = subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', spec], timeout=20)
        if len(sources[name]) != length:
            raise RuntimeError('A pinned source blob changed size.')
    root = home / '.local/state/kiani-instagram-news-ranking/source' / args.revision
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in sources.items():
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned source file differs; no overwrite performed.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            with path.open('xb') as handle:
                handle.write(data)
    print(f'Extracted/verified {len(FILES)} files ({size / 1024:.1f} KiB); no repository checkout.', flush=True)
    python = home / 'kiani-instagram-venv/bin/python'
    if args.activate:
        command = [str(python), '-u', str(root / 'deploy/instagram-news/activate_ranked_news.py'),
                   '--runtime', str(root), '--revision', args.revision]
    else:
        command = [str(python), '-u', str(root / 'instagram_ranked_news.py'), '--kind', args.kind]
        print('Preview only: ranks both categories and renders up to two separate posts each.', flush=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul')
    with (home / 'kiani-instagram-ranked-news.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', cwd=root, env=env)
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            return process.wait()
        except BaseException:
            process.terminate()
            raise


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else f'Ranked-news setup stopped ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)
