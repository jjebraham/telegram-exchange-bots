"""Prepare an opt-in official TGJU API route without replacing dirty fetchers.

Dry run is the default. --apply backs up both files, inserts only a guarded
function-local transport branch and copies the reviewed API client. It does
not enable the route, touch .env, change safety, restart or publish anything.
"""
from __future__ import annotations
import argparse,ast,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

SPECS=(('iran_fx.py','fetch_iran_open_market_fx','TGJU_CURRENCY_URL','fetch_iran_fx_public'),
       ('iran_gold.py','fetch_iran_gold_market','TGJU_HOME_URL','fetch_iran_gold_public'))

def add_hook(raw: bytes, function: str, default_url: str, helper: str) -> bytes:
    source=raw.decode('utf-8')
    tree=ast.parse(source)
    matches=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==function]
    if len(matches)!=1 or [arg.arg for arg in matches[0].args.args]!=['url','timeout']:
        raise ValueError('Unexpected fetcher signature: '+function)
    node=matches[0]
    newline='\r\n' if '\r\n' in source else '\n'
    hook=('\n    # AlanChande official API transport (opt-in)\n'
          '    import os as _alan_transport_os\n'
          '    if (_alan_transport_os.environ.get("ALANCHANDE_TGJU_TRANSPORT", "html") in {"public_api", "akamai_api"}\n'
          f'            and url == {default_url}):\n'
          f'        from tgju_public_api import {helper}\n'
          f'        return {helper}(timeout=timeout)\n').replace('\n',newline)
    if 'AlanChande official API transport (opt-in)' in source:
        if source.count(hook)==1:
            return raw
        legacy=hook.replace('in {"public_api", "akamai_api"}', '== "public_api"')
        if source.count(legacy)==1:
            return source.replace(legacy,hook,1).encode('utf-8')
        raise ValueError('Existing transport hook differs; review manually')
    first=node.body[0]
    doc=isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant) and isinstance(first.value.value,str)
    insertion=first.end_lineno if doc else first.lineno-1
    lines=source.splitlines(keepends=True)
    changed=''.join(lines[:insertion])+hook+''.join(lines[insertion:])
    ast.parse(changed)
    return changed.encode('utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=Path('/home/kianirad2020/telegram_bot_repo'))
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    repo=args.repo.resolve()
    folder=(repo/'channel_split').resolve()
    if not folder.is_relative_to(repo):
        raise SystemExit('STOP: target folder is outside the named repository')
    sources={name:Path(__file__).with_name(name).read_bytes()
             for name in ('tgju_public_api.py','tgju_akamai.py')}
    for client in sources.values():
        ast.parse(client.decode('utf-8'))
    originals={}; replacements={}
    for filename,function,default_url,helper in SPECS:
        path=folder/filename
        raw=path.read_bytes()
        originals[path]=raw
        replacements[path]=add_hook(raw,function,default_url,helper)
    for name,client in sources.items():
        target=folder/name
        if target.is_symlink():
            raise SystemExit('STOP: API client is a symlink')
        originals[target]=target.read_bytes() if target.exists() else None
        known_prior = name=='tgju_public_api.py' and originals[target] is not None and hashlib.sha256(
            originals[target].replace(b'\r\n',b'\n')).hexdigest() == '3fc25cbf5ea6503eae8a9e527aebdeea5c0b41d25d5591d50a03671ff7330207'
        if originals[target] not in (None,client) and not known_prior:
            raise SystemExit('STOP: an unrecognized API client already exists; review manually')
        replacements[target]=client
    changes={path:raw for path,raw in replacements.items() if raw!=originals[path]}
    print(json.dumps({'mode':'apply' if args.apply else 'dry-run',
                      'files':[{'name':path.name,'sha256':hashlib.sha256(raw).hexdigest()} for path,raw in changes.items()],
                      'transport_enabled':False},indent=2))
    if not args.apply or not changes:
        return 0
    backup_root=args.backup_dir.resolve() if args.backup_dir else repo.parent/'alanchande-tgju-api-backups'
    backup=backup_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    for path,raw in originals.items():
        if raw is not None:
            (backup/path.name).write_bytes(raw)
    written=[]
    try:
        for path,raw in changes.items():
            current=path.read_bytes() if path.exists() else None
            if current!=originals[path]:
                raise RuntimeError('Concurrent change detected: '+path.name)
            temp=path.with_name(path.name+'.api-next-'+uuid4().hex)
            try:
                temp.write_bytes(raw)
                if path.exists():
                    temp.chmod(path.stat().st_mode & 0o777)
                os.replace(temp,path)
                written.append(path)
            finally:
                if temp.exists():
                    temp.unlink()
    except Exception:
        for path in reversed(written):
            if originals[path] is None:
                path.unlink()
            else:
                path.write_bytes(originals[path])
        raise
    print('BACKUP:',backup)
    print('PREPARED ONLY: ALANCHANDE_TGJU_TRANSPORT is unchanged; no publication or restart')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
