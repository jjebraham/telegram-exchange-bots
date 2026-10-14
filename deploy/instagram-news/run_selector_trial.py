#!/usr/bin/env python3
"""Run the preview trial from an isolated pinned checkout, without deployment."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


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
    work = Path(tempfile.mkdtemp(prefix='kiani-news-selector-trial.'))
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(work), args.revision], check=True, timeout=60)
    print('Trial checkout:', work, flush=True)
    print('Using the existing DeepSeek key for article assessment and winner translation.', flush=True)
    print('No Instagram credentials loaded. This launcher has no publish or activation action.', flush=True)
    log = home / 'kiani-news-selector-trial.log'
    # Keep audit/cache private. The child explicitly makes only JPEG output public-readable.
    os.umask(0o077)
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
        print(f'Trial launcher failed ({type(exc).__name__}); no schedule activated.', file=sys.stderr)
        raise SystemExit(1)
