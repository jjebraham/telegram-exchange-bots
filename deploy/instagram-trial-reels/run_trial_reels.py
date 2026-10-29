#!/usr/bin/env python3
"""Extract a pinned Trial Reel runtime and optionally activate its schedules."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = (
    'instagram_manual_news_intake.py',
    'instagram_trial_reels.py',
    'instagram_trial_music.py',
    'instagram_ranked_news.py',
    'crypto_news_trial.py',
    'instagram_news_batch.py',
    'instagram_insights_data.py',
    'instagram_news_retention.py',
    'selector_trial_runtime/economy_news_picker.py',
    'selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py',
    'selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md',
    'deploy/instagram-trial-reels/activate_trial_reels.py',
    'deploy/instagram-trial-reels/TRIAL-REELS.md',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing Instagram publisher user, without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Supply the exact reviewed revision.')
    os.umask(0o077)
    home = Path.home()
    if shutil.disk_usage(home).free < 256 * 1024**2:
        raise RuntimeError('At least 256 MiB free is required for safe rendering and state writes.')
    repo = args.repo.expanduser().resolve()
    sources, size = {}, 0
    for name in FILES:
        spec = args.revision + ':' + name
        length = int(subprocess.check_output(['git', '-C', str(repo), 'cat-file', '-s', spec], timeout=20))
        size += length
        if length <= 0 or size > 4 * 1024**2:
            raise RuntimeError('Pinned source extraction exceeded its size limit.')
        sources[name] = subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', spec], timeout=20)
        if len(sources[name]) != length:
            raise RuntimeError('A pinned source file changed size during extraction.')
    root = home / '.local/state/kiani-instagram-manual-news/source' / args.revision
    if root.is_symlink():
        raise RuntimeError('The pinned runtime directory is unsafe.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    for name, data in sources.items():
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned source file differs; no overwrite performed.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            with path.open('xb') as handle:
                handle.write(data)
            path.chmod(0o600)
    print(f'Extracted/verified {len(FILES)} files ({size / 1024:.1f} KiB); no repository checkout.', flush=True)
    if args.install:
        python = home / 'kiani-instagram-venv/bin/python'
        command = [str(python), '-u', str(root / 'deploy/instagram-trial-reels/activate_trial_reels.py'),
                   '--runtime', str(root), '--revision', args.revision]
        env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul')
        return subprocess.run(command, check=False, cwd=root, env=env).returncode
    print('Runtime prepared only. Add --install to activate the admin command and daily schedule.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
              f'Trial Reel setup stopped ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)

