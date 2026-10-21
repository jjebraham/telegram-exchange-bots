#!/usr/bin/env python3
"""Extract and run a pinned, small read-only Instagram analytics release."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = ('instagram_insights_data.py', 'instagram_post_insights.py',
         'instagram_news_retention.py', 'instagram_news_batch.py', 'instagram_ranked_news.py', 'crypto_news_trial.py',
         'selector_trial_runtime/economy_news_picker.py', 'selector_trial_runtime/economy_news_translation.py',
         'selector_trial_runtime/instagram_crypto_news.py', 'selector_trial_runtime/instagram_news_renderer.py',
         'selector_trial_runtime/PINNED.md', 'deploy/instagram-news/activate_ranked_news.py',
         'deploy/instagram-rates/setup_long_lived_token.py', 'deploy/instagram-insights/audit_permissions.py',
         'deploy/instagram-insights/run_insights.py',
         'deploy/instagram-insights/activate_insights.py', 'deploy/instagram-insights/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--activate', action='store_true')
    actions.add_argument('--audit-permissions', action='store_true')
    actions.add_argument('--renew-token', action='store_true')
    actions.add_argument('--preview-news', action='store_true')
    parser.add_argument('--news-batch', action='store_true')
    parser.add_argument('--news-retention', action='store_true')
    parser.add_argument('--declare-organic', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0 or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Use the existing publisher user without sudo and a reviewed 40-character revision.')
    if args.activate and args.declare_organic:
        parser.error('Use --declare-organic only with the initial read-only probe.')
    if (args.news_batch or args.news_retention) and not args.activate:
        parser.error('News policy activation switches require --activate.')
    if args.declare_organic and (args.audit_permissions or args.preview_news or args.renew_token):
        parser.error('Use --declare-organic only with the initial read-only probe.')
    os.umask(0o077)
    home = Path.home()
    if shutil.disk_usage(home).free < 64 * 1024**2:
        raise RuntimeError('At least 64 MiB free is required for the private analytics database.')
    env_path = home / '.kiani-instagram.env'
    if env_path.is_symlink() or not env_path.is_file() or env_path.stat().st_uid != os.getuid():
        raise RuntimeError('Existing private publisher configuration is missing or has an unexpected owner.')
    python = home / 'kiani-instagram-venv/bin/python'
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError('The existing publisher Python runtime is missing.')
    root, sources, total = home / '.local/state/kiani-instagram-insights/source' / args.revision, {}, 0
    for name in FILES:
        spec = args.revision + ':' + name
        size = int(subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', '-s', spec], timeout=20))
        total += size
        if size <= 0 or total > 512 * 1024:
            raise RuntimeError('Pinned analytics extraction exceeded its source size limit.')
        data = subprocess.check_output(['git', '-C', str(args.repo), 'cat-file', 'blob', spec], timeout=20)
        if len(data) != size:
            raise RuntimeError('Pinned source blob size mismatch.')
        sources[name] = data
    for name, data in sources.items():
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned analytics source differs.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            path.write_bytes(data)
    if args.activate:
        command = [str(python), '-u', str(root / 'deploy/instagram-insights/activate_insights.py'),
                   '--runtime', str(root), '--revision', args.revision]
        if args.news_batch:
            command.append('--news-batch')
        if args.news_retention:
            command.append('--news-retention')
    elif args.audit_permissions:
        command = [str(python), '-u', str(root / 'deploy/instagram-insights/audit_permissions.py')]
    elif args.renew_token:
        command = [str(python), '-u', str(root / 'deploy/instagram-rates/setup_long_lived_token.py'),
                   '--preserve-current-scopes', '--require-scope', 'instagram_basic',
                   '--require-scope', 'instagram_manage_insights', '--require-scope', 'instagram_manage_contents']
    elif args.preview_news:
        command = [str(python), '-u', str(root / 'instagram_ranked_news.py'), '--kind', 'both']
    else:
        command = [str(python), '-u', str(root / 'instagram_post_insights.py'), '--probe']
        if args.declare_organic:
            command.append('--declare-organic')
    print(f'Extracted/verified {len(FILES)} files ({total / 1024:.1f} KiB); no repository checkout.', flush=True)
    print('Activating the requested, verified analytics/news policies.' if args.activate else
          'Permission audit only; no content changes.' if args.audit_permissions else
          'Token renewal only: preserve existing grants and verify the two new permissions before saving. No publishing or deletion.' if args.renew_token else
          'News preview only; no Instagram content changes.' if args.preview_news else
          'Read-only Meta insights/quota probe. Existing posts and schedules are not modified.', flush=True)
    # The script is static; secrets are sourced without echoing and passed in the
    # process environment. No credential is interpolated into shell text or URLs.
    shell = 'set -euo pipefail; set -a; . "$HOME/.kiani-instagram.env"; set +a; exec "$@"'
    return subprocess.run(['/bin/bash', '-c', shell, 'kiani-insights', *command], cwd=root,
        env=dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Asia/Tehran')).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
