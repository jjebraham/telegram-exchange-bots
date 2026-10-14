#!/usr/bin/env python3
"""Run the preview trial from only its pinned source files, without deployment."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

FILES = (
    'crypto_news_trial.py',
    'selector_trial_runtime/economy_news_picker.py',
    'selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py',
    'selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md',
    'diagnostics/instagram_post_audit.py',
    'diagnostics/record_news_metrics.py',
    'deploy/instagram-news/SELECTOR-TRIAL.md',
)
RESERVE = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def extract_sources(repo, revision):
    """Read an exact allowlist of Git blobs; never check out the repository."""
    files = {}
    total = 0
    for name in FILES:
        spec = revision + ':' + name
        size = int(subprocess.check_output(
            ['git', '-C', str(repo), 'cat-file', '-s', spec], timeout=20))
        total += size
        if size <= 0 or total > MAX_SOURCE_BYTES:
            raise RuntimeError('Trial source exceeds its extraction size limit.')
        data = subprocess.check_output(
            ['git', '-C', str(repo), 'cat-file', 'blob', spec], timeout=20)
        if len(data) != size:
            raise RuntimeError('A trial source blob has an unexpected size.')
        files[name] = data
    temp_root = Path(tempfile.gettempdir()).resolve()
    for path in (temp_root, Path.home(), Path('/var/www/peerexo.com/public/instagram-rates')):
        if not path.is_dir() or shutil.disk_usage(path).free < RESERVE:
            raise RuntimeError('At least 64 MiB of free space is required for trial data and preview images.')
    work = Path(tempfile.mkdtemp(prefix='kiani-news-selector-files.', dir=temp_root))
    for name, data in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open('xb') as handle:
            handle.write(data)
    (work / 'revision.txt').write_text(revision + '\n', encoding='utf-8')
    print(f'Extracted {len(files)} trial files ({total / 1024:.1f} KiB).', flush=True)
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{40}', args.revision):
        parser.error('Supply the reviewed exact commit SHA.')
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run on Selenium as the existing publisher user, without sudo.')
    home = Path.home()
    python = home / 'kiani-instagram-venv/bin/python'
    env_file = home / 'sub/.env'
    if not python.is_file() or not env_file.is_file():
        raise RuntimeError('The existing Python/DeepSeek configuration is missing.')
    repo = args.repo.expanduser().resolve()
    resolved = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', args.revision + '^{commit}'],
                                       text=True, timeout=20).strip()
    if resolved != args.revision:
        raise RuntimeError('The requested revision could not be verified.')
    # Keep source snapshots, audits and the log private. The trial explicitly
    # switches permission defaults only while generating public preview images.
    os.umask(0o077)
    work = extract_sources(repo, args.revision)
    print('Trial source directory:', work, flush=True)
    print('Using the existing DeepSeek key for article assessment and winner translation.', flush=True)
    print('No Instagram credentials loaded. This launcher has no publish or activation action.', flush=True)
    log = home / 'kiani-news-selector-trial.log'
    env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul')
    command = [str(python), '-u', str(work / 'crypto_news_trial.py')]
    with log.open('a', encoding='utf-8') as handle:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', env=env, cwd=work)
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                handle.write(line)
                handle.flush()
            result = process.wait()
        except BaseException:
            process.terminate()
            raise
    print('Trial log:', log, flush=True)
    return result


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'Trial launcher failed: {message}. No schedule activated.', file=sys.stderr)
        raise SystemExit(1)
