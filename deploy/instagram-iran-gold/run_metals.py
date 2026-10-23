#!/usr/bin/env python3
"""Small pinned global-metals preview and activation; no immediate publication."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = ('iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py','instagram_iran_gold.py',
    'instagram_iran_gold_renderer.py','global_metals_data.py','instagram_global_metals_renderer.py',
    'economic_calendar_data.py','instagram_economic_calendar_renderer.py',
    'tests/test_instagram_iran_gold.py','tests/test_iran_gold_servix.py','tests/test_iran_gold_template.py',
    'assets/instagram/gold-coin.png','assets/instagram/gold-bars.png',
    'deploy/instagram-iran-gold/activate_servix.py','deploy/instagram-iran-gold/activate_template.py',
    'deploy/instagram-iran-gold/activate_metals.py','deploy/instagram-iran-gold/run_metals.py',
    'deploy/instagram-iran-gold/README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.home()/'telegram_bot_repo')
    parser.add_argument('--revision',required=True)
    parser.add_argument('--activate',action='store_true')
    args = parser.parse_args()
    if not hasattr(os,'geteuid') or os.geteuid()==0 or not re.fullmatch('[0-9a-f]{40}',args.revision):
        parser.error('Use the reviewed revision as the publisher user, without sudo.')
    os.umask(0o077)
    home, sources, total = Path.home(), {}, 0
    for p in (home,Path('/var/www/peerexo.com/public/instagram-rates')):
        if not p.is_dir() or shutil.disk_usage(p).free < 128*1024**2:
            raise RuntimeError('At least 128 MiB free is required for price data and images.')
    for name in FILES:
        spec = args.revision+':'+name
        size = int(subprocess.check_output(['git','-C',str(args.repo),'cat-file','-s',spec],timeout=20))
        total += size
        if size<=0 or total>512*1024:
            raise RuntimeError('Pinned extraction exceeded its size limit.')
        data = subprocess.check_output(['git','-C',str(args.repo),'cat-file','blob',spec],timeout=20)
        if len(data)!=size:
            raise RuntimeError('Pinned blob size differs.')
        sources[name]=data
    root = home/'.local/state/kiani-instagram-iran-gold/source'/args.revision
    for name,data in sources.items():
        p = root/name
        if p.is_symlink() or p.exists() and p.read_bytes()!=data:
            raise RuntimeError('An existing pinned source differs.')
        p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not p.exists():
            p.write_bytes(data)
    python = home/'kiani-instagram-venv/bin/python'
    env = dict(os.environ,PYTHONIOENCODING='utf-8',TZ='Asia/Tehran')
    def run(command):
        subprocess.run(command,cwd=root,env=env,check=True)
    app = [str(python),'-u',str(root/'instagram_iran_gold.py')]
    print(f'Extracted/verified {len(FILES)} files ({total/1024:.1f} KiB); no repository checkout.',flush=True)
    print('Checking the existing gold/template safeguards without Meta contact.',flush=True)
    run(app+['--self-check'])
    print('Collecting fresh sources and rendering a required TWO-slide preview. No Meta contact.',flush=True)
    run(app+['--require-metals'])
    if args.activate:
        run([str(python),'-u',str(root/'deploy/instagram-iran-gold/activate_metals.py'),
             '--runtime',str(root),'--revision',args.revision])
    print('No immediate Instagram post was published by this command.',flush=True)
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
