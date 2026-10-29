"""Select only locally reviewed, explicitly licensed illustrative media."""
from pathlib import Path
import hashlib
import json
import re
from urllib.parse import urlsplit

ROOT=Path.home()/'.local/state/kiani-instagram-trial-reels/approved-media'
LICENSES={'CC BY 4.0':'https://creativecommons.org/licenses/by/4.0/',
          'CC0 1.0':'https://creativecommons.org/publicdomain/zero/1.0/'}

def select(story, root=None):
    root=Path(root or ROOT)
    if not root.exists(): return []
    if root.is_symlink() or not root.is_dir(): raise ValueError('Unsafe approved media directory')
    manifest=root/'manifest.json'
    if not manifest.exists(): return []
    if manifest.is_symlink() or manifest.stat().st_size>100000: raise ValueError('Unsafe approved media manifest')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data,list) or len(data)>200: raise ValueError('Invalid approved media manifest')
    title=(story.get('title_original','')+' '+story.get('title_fa','')).casefold()
    chosen=[]
    for item in data:
        if not isinstance(item,dict) or item.get('approved') is not True or item.get('illustrative') is not True: continue
        keywords=item.get('keywords')
        if not isinstance(keywords,list) or not any(isinstance(k,str) and len(k)>=3 and k.casefold() in title for k in keywords): continue
        name=item.get('file',''); license_name=item.get('license'); author=item.get('author',''); url=item.get('source_url',''); expected=item.get('sha256','')
        if not isinstance(name,str) or Path(name).name!=name or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}\.(jpg|jpeg|png|webp)',name,re.I): continue
        if license_name not in LICENSES or not isinstance(author,str) or not 1<=len(author.strip())<=100 or any(x in author for x in '\n\r<>'): continue
        if not isinstance(url,str) or len(url)>500 or urlsplit(url).scheme!='https' or not urlsplit(url).hostname: continue
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected): continue
        path=root/name
        if path.is_symlink() or not path.is_file() or not 1000<=path.stat().st_size<=15*1024*1024: continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: continue
        chosen.append({'path':path,'author':author.strip(),'license':license_name,'license_url':LICENSES[license_name],'source_url':url})
        if len(chosen)>=3: break
    return chosen

def caption(selected):
    return '\n'.join('Illustrative image: '+x['author']+'; '+x['license']+'; cropped. '+x['source_url']+' '+x['license_url'] for x in selected)

