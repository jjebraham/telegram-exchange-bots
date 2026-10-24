#!/usr/bin/env python3
"""Preview or activate the approved readable layout for both hourly news feeds."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

RUNTIME = ('instagram_ranked_news.py','crypto_news_trial.py','instagram_news_batch.py','instagram_insights_data.py',
    'selector_trial_runtime/economy_news_picker.py','selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py','selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md')
FILES = RUNTIME + ('deploy/instagram-news-carousel/run_carousel.py',
    'deploy/instagram-news-carousel/activate_carousel.py','deploy/instagram-news-carousel/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home()/'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--kind', choices=('both','crypto','economy'), default='both')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--layout-preview', action='store_true',
                        help='Render an already-published story read-only to verify layout when no fresh story qualifies.')
    args = parser.parse_args()
    if args.activate and args.layout_preview:
        parser.error('Layout preview and activation are separate actions.')
    if not hasattr(os,'geteuid') or os.geteuid() == 0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        parser.error('Use the pinned revision as the existing publisher user, without sudo.')
    os.umask(0o077)
    home = Path.home()
    public = Path('/var/www/peerexo.com/public/instagram-rates')
    if any(not p.is_dir() or shutil.disk_usage(p).free < 128*1024**2 for p in (home,public)):
        raise RuntimeError('At least 128 MiB free is required for the preview and release.')
    root = home/'.local/state/kiani-instagram-news-carousel/source'/args.revision
    sources, total = {}, 0
    for name in FILES:
        spec = args.revision+':'+name
        size = int(subprocess.check_output(['git','-C',str(args.repo),'cat-file','-s',spec],timeout=20))
        total += size
        if not 0 < size or total > 512*1024:
            raise RuntimeError('Pinned source extraction exceeded its bound.')
        raw = subprocess.check_output(['git','-C',str(args.repo),'cat-file','blob',spec],timeout=20)
        if len(raw) != size:
            raise RuntimeError('Pinned source length differs.')
        sources[name] = raw
    for name,raw in sources.items():
        path = root/name
        if path.is_symlink() or path.exists() and path.read_bytes() != raw:
            raise RuntimeError('An existing pinned source differs: '+name)
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not path.exists():
            path.write_bytes(raw)
    python = home/'kiani-instagram-venv/bin/python'
    if args.activate or args.layout_preview:
        command = [str(python),'-u',str(root/'deploy/instagram-news-carousel/activate_carousel.py'),
                   '--runtime',str(root),'--revision',args.revision]
        if args.layout_preview:
            command += ['--layout-preview','--kind',args.kind]
    else:
        command = [str(python),'-u',str(root/'instagram_ranked_news.py'),'--kind',args.kind,
                   '--publisher-root',str(home/'kiani-instagram-publisher')]
    print(f'Extracted/verified {len(FILES)} files ({total/1024:.1f} KiB); no repository checkout.',flush=True)
    print('Activating approved Option B news layout.' if args.activate else
          'Layout-only historical preview. Read-only completed publication; no Meta API contact or publication.' if args.layout_preview else
          'Preview only: fresh verified/ranked news, readable carousel. No Meta API contact or publication.',flush=True)
    return subprocess.run(command,cwd=root,env=dict(os.environ,PYTHONIOENCODING='utf-8',TZ='Europe/Istanbul')).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('News carousel launcher stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
