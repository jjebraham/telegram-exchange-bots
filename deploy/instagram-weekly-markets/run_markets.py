#!/usr/bin/env python3
"""Extract a small pinned source set, read live prices, optionally activate."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess

FILES=('weekly_market_data.py','instagram_weekly_markets.py','instagram_weekly_markets_renderer.py',
       'iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py','economic_calendar_data.py',
       'instagram_economic_calendar_renderer.py','assets/instagram/gold-coin.png','assets/instagram/gold-bars.png',
       'instagram_delayed_stories.py','instagram_story_renderer.py','instagram_insights_data.py',
       'instagram_post_insights.py','instagram_news_retention.py','deploy/instagram-weekly-markets/activate_markets.py',
       'deploy/instagram-weekly-markets/run_markets.py','deploy/instagram-weekly-markets/README.md')


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--repo',type=Path,default=Path.home()/'telegram_bot_repo')
    p.add_argument('--revision',required=True); p.add_argument('--activate',action='store_true'); args=p.parse_args()
    if not hasattr(os,'geteuid') or os.geteuid()==0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        p.error('Use the pinned revision as the existing publisher user without sudo.')
    os.umask(0o077); home=Path.home(); blobs={}; total=0
    for path in (home,Path('/var/www/peerexo.com/public/instagram-rates')):
        if not path.is_dir() or shutil.disk_usage(path).free<128*1024**2: raise RuntimeError('128 MiB free is required.')
    for name in FILES:
        spec=args.revision+':'+name; size=int(subprocess.check_output(['git','-C',str(args.repo),'cat-file','-s',spec],timeout=20))
        total+=size
        if size<=0 or total>512*1024: raise RuntimeError('Pinned extraction exceeded its size limit.')
        raw=subprocess.check_output(['git','-C',str(args.repo),'cat-file','blob',spec],timeout=20)
        if len(raw)!=size: raise RuntimeError('Pinned source blob size differs.')
        blobs[name]=raw
    root=home/'.local/state/kiani-instagram-weekly-markets/source'/args.revision
    for name,raw in blobs.items():
        path=root/name
        if path.is_symlink() or path.exists() and path.read_bytes()!=raw: raise RuntimeError('An existing pinned source differs.')
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not path.exists(): path.write_bytes(raw)
    python=home/'kiani-instagram-venv/bin/python'; env=dict(os.environ,PYTHONIOENCODING='utf-8',TZ='Asia/Tehran')
    print(f'Extracted/verified {len(FILES)} files ({total/1024:.1f} KiB); no repository checkout.',flush=True)
    print('Live five-market source preflight only. No Meta API contact or historical backfill.',flush=True)
    subprocess.run([str(python),'-u',str(root/'instagram_weekly_markets.py')],cwd=root,env=env,check=True)
    if args.activate:
        subprocess.run([str(python),'-u',str(root/'deploy/instagram-weekly-markets/activate_markets.py'),
            '--runtime',str(root),'--revision',args.revision],cwd=root,env=env,check=True)
    print('Nothing published or deleted by this command.',flush=True)
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Weekly launcher stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
        raise SystemExit(1)
