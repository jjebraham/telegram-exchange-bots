#!/usr/bin/env python3
"""Configure free stock API keys privately and run a non-publishing check."""
from pathlib import Path
import argparse
import getpass
import os
import re
import sys
import tempfile
import warnings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    runtime=parser.parse_args().runtime.resolve()
    sys.path[:0]=[str(runtime),str(runtime/'selector_trial_runtime')]
    import instagram_reel_stock as stock
    warnings.simplefilter('error',getpass.GetPassWarning)
    config=stock.CONFIG
    if config.is_symlink() or not config.is_dir() or config.stat().st_uid!=os.getuid() or config.stat().st_mode & 0o077:
        raise RuntimeError('Existing private config directory needs review.')
    if stock.STATE.is_symlink() or not stock.STATE.is_dir() or stock.STATE.stat().st_uid!=os.getuid():
        raise RuntimeError('Existing private Reel state directory needs review.')
    for provider in ('pexels','pixabay'):
        if stock._key(provider):
            print(provider.capitalize()+': existing private key found',flush=True)
            continue
        path=config/(provider+'-api-key')
        if path.exists() or path.is_symlink():
            raise RuntimeError(provider.capitalize()+' key file exists but needs permission review.')
        key=getpass.getpass(provider.capitalize()+' API key (hidden; Enter to skip): ').strip()
        if not key:
            print(provider.capitalize()+': skipped; existing image sources remain available',flush=True)
            continue
        if not 8 <= len(key) <= 256 or not re.fullmatch(r'[A-Za-z0-9_-]+',key):
            raise RuntimeError(provider.capitalize()+' key format is invalid.')
        try:
            from contextlib import closing
            with closing(stock._database()) as con:
                data=stock._api(provider,'bitcoin cryptocurrency',key,con,__import__('time').time(),bypass_cache=True)
            if not stock._candidates(provider,data):
                raise RuntimeError('No usable search results.')
        except Exception as exc:
            print(provider.capitalize()+' connection check failed:',type(exc).__name__,flush=True)
            raise RuntimeError('No new key saved for this provider.') from None
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as h:
            h.write(key+'\n')
        print(provider.capitalize()+': key verified and saved privately',flush=True)
    with tempfile.TemporaryDirectory(prefix='kiani-stock-preview-') as tmp:
        counts={}
        configured=[p for p in ('pexels','pixabay') if stock._key(p)]
        if not configured:
            raise RuntimeError('No stock API keys were configured.')
        for provider in configured:
            folder=Path(tmp)/provider
            folder.mkdir()
            found=stock.collect({'title_original':'bitcoin cryptocurrency security'},folder,
                                origin='admin_direct',limit=1,provider_filter={provider})
            counts[provider]=len(found)
        print('Sample validated images:',counts,flush=True)
        if not all(counts.values()):
            raise RuntimeError('Could not verify at least one image from each provider.')
    print('Private stock preflight passed. No DeepSeek or Instagram request was made.',flush=True)

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Stock setup stopped:',type(exc).__name__,str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
