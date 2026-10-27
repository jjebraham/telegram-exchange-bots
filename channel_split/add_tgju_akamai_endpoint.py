#!/usr/bin/env python3
"""Add one fixed TGJU selector to the existing Akamai bridge. Dry-run by default.

Run on Akamai 139.162.186.28 through its established administrator connection.
No keys, SSH restrictions, existing endpoints, pricing rules or services change.
This does not install or activate Telegram image publishing.
"""
from __future__ import annotations
import argparse,ast,hashlib,json,os,re,stat,tempfile,unittest
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from uuid import uuid4

BRIDGE=Path('/opt/kiani-rate-bridge/bridge.py')
SELECTOR='tgju_current'
URL='https://call4.tgju.org/ajax.json?rev=alanchande_live_v1'
SYMBOLS=('price_dollar_rl','price_eur','price_gbp','price_chf','price_cad','price_aud',
         'price_sek','price_nok','price_rub','price_thb','price_sgd','price_hkd','price_azn',
         'price_dkk','price_aed','price_try','price_cny','price_sar','price_inr','price_myr',
         'price_afn','price_kwd','price_bhd','price_omr','price_qar',
         'sekee','sekeb','nim','rob','gerami','geram18','mesghal')

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def patch_bridge(raw):
    source=raw.decode('utf-8'); tree=ast.parse(source)
    nodes=[node for node in tree.body if isinstance(node,ast.Assign)
           and any(isinstance(target,ast.Name) and target.id=='URLS' for target in node.targets)]
    if len(nodes)!=1:
        raise ValueError('Existing bridge URLS map is missing or ambiguous')
    node=nodes[0]; original=ast.literal_eval(node.value)
    if not isinstance(original,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in original.items()):
        raise ValueError('Existing URLS map is not a literal string map')
    if SELECTOR in original:
        if original[SELECTOR]!=URL:
            raise ValueError('TGJU selector already differs; manual review required')
        return raw
    lines=source.splitlines(keepends=True)
    replacement=dict(original); replacement[SELECTOR]=URL
    lines[node.lineno-1:node.end_lineno]=['URLS = '+repr(replacement)+'\n']
    changed=''.join(lines).encode('utf-8'); after=ast.parse(changed)
    tree.body.remove(node)
    after.body=[entry for entry in after.body if not (isinstance(entry,ast.Assign)
                and any(isinstance(target,ast.Name) and target.id=='URLS' for target in entry.targets))]
    if ast.dump(tree,include_attributes=False)!=ast.dump(after,include_attributes=False):
        raise ValueError('Proposed change escapes the fixed endpoint map')
    compile(changed,str(BRIDGE),'exec')
    return changed

def validate_prices(payload):
    current=payload.get('current') if isinstance(payload,dict) else None
    if not isinstance(current,dict):
        raise ValueError('Official API has no current-price map')
    for symbol in SYMBOLS:
        item=current.get(symbol); value=item.get('p') if isinstance(item,dict) else None
        if (not isinstance(value,str)
                or not re.fullmatch(r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)',value)
                or int(value.replace(',',''))<=0):
            raise ValueError('Official API is missing a positive required price: '+symbol)
    return len(SYMBOLS)

def probe():
    request=Request(URL,headers={'Accept':'application/json','Cache-Control':'no-cache',
                                'Pragma':'no-cache','Accept-Encoding':'identity'})
    with build_opener(ProxyHandler({})).open(request,timeout=15) as response:
        if response.status!=200:
            raise ValueError('Official API did not return HTTP 200')
        raw=response.read(2_000_001)
        headers={key.lower():response.headers.get(key) for key in ('Date','Age')}
    if len(raw)>2_000_000:
        raise ValueError('Official API exceeds response size limit')
    now=datetime.now(timezone.utc)
    http_date=parsedate_to_datetime(headers['date'])
    if http_date.tzinfo is None or not -5<=(now-http_date).total_seconds()<=90:
        raise ValueError('Official API HTTP date is missing, stale or in the future')
    if not 0<=float(headers['age'] or '0')<=30:
        raise ValueError('Official API response cache age is too old')
    count=validate_prices(json.loads(raw))
    return {'http_status':200,'required_positive_prices':count,
            'observed_at_utc':now.isoformat(),'sha256':digest(raw)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(PatchTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    for path in (BRIDGE,*BRIDGE.parents):
        if path.is_symlink():
            raise ValueError('Bridge or parent is a symlink; manual review required')
    info=BRIDGE.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
        raise ValueError('Bridge must be a regular root-owned file without group/world write permission')
    original=BRIDGE.read_bytes(); changed=patch_bridge(original)
    proof=probe()
    print(json.dumps({'mode':'apply' if args.apply else 'dry-run','selector':SELECTOR,
                      'fixed_url':URL,'only_url_map_changes':True,'source_probe':proof,
                      'original_sha256':digest(original),'proposed_sha256':digest(changed)},indent=2),flush=True)
    if not args.apply or changed==original:
        return 0
    if os.geteuid()!=0:
        raise PermissionError('Applying the reviewed bridge update requires its administrator')
    backup=Path('/var/backups/alanchande-tgju')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    saved=backup/'bridge.py'; saved.write_bytes(original); saved.chmod(0o600)
    (backup/'manifest.json').write_text(json.dumps({'target':str(BRIDGE),'original_sha256':digest(original),
         'new_sha256':digest(changed),'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode)},indent=2)+'\n')
    if BRIDGE.read_bytes()!=original:
        raise RuntimeError('Concurrent bridge change detected; nothing installed')
    fd,name=tempfile.mkstemp(prefix='.alanchande-tgju-',dir=BRIDGE.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(changed);stream.flush();os.fsync(stream.fileno())
            os.fchown(stream.fileno(),info.st_uid,info.st_gid)
            os.fchmod(stream.fileno(),stat.S_IMODE(info.st_mode))
        os.replace(name,BRIDGE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('INSTALLED one fixed endpoint; BACKUP:',backup,flush=True)
    print('No SSH key/restriction, service, pricing rule or Telegram setting changed.',flush=True)
    return 0

class PatchTests(unittest.TestCase):
    def test_only_one_fixed_endpoint_added_and_idempotent(self):
        raw=b'#!/usr/bin/env python3\nURLS = {"btcturk_usdt_try":"https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"}\n\ndef fetch(selector):\n    if selector not in URLS: raise ValueError("unknown endpoint selector")\n    return URLS[selector]\n'
        changed=patch_bridge(raw); namespace={};exec(compile(changed,'fixture','exec'),namespace)
        self.assertEqual(namespace['fetch'](SELECTOR),URL)
        self.assertEqual(namespace['fetch']('btcturk_usdt_try'),'https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY')
        with self.assertRaises(ValueError):namespace['fetch']('https://unapproved.invalid')
        self.assertEqual(patch_bridge(changed),changed)
    def test_conflicting_or_ambiguous_map_stops(self):
        for raw in (b'URLS={"tgju_current":"https://different.invalid"}\n',b'URLS={}\nURLS={}\n',b'URLS=dynamic()\n'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,TypeError)):
                patch_bridge(raw)
    def test_required_prices_fail_closed(self):
        payload={'current':{symbol:{'p':'1,000'} for symbol in SYMBOLS}}
        self.assertEqual(validate_prices(payload),32)
        for invalid in (None,True,'NaN','-1','0','1,23'):
            payload['current']['sekee']['p']=invalid
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_prices(payload)
        del payload['current']['sekee']
        with self.assertRaises(ValueError):validate_prices(payload)

if __name__=='__main__':
    raise SystemExit(main())
