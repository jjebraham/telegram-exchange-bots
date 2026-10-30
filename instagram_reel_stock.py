"""Optional Pexels/Pixabay illustrations for Instagram Reels."""
from __future__ import annotations
import hashlib
from contextlib import closing
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from PIL import Image, ImageOps

CONFIG = Path.home()/'.config/kiani-instagram-manual-news'
STATE = Path.home()/'.local/state/kiani-instagram-trial-reels'
MAX_IMAGE = 10_000_000
API_LIMIT = 1_500_000
HISTORY_DAYS = 30
UA = 'KianiExchangeInstagramReels/1.0 (https://kiani.exchange)'
TOPICS = (
    (r'\bhack(?:er|ers|ing|ed)?\b|\bphish|cyber|security|\bfraud\b|\bscam', ('cyber security', 'computer network security')),
    (r'\bbitcoin\b|\bbtc\b', ('bitcoin cryptocurrency', 'cryptocurrency trading')),
    (r'\bethereum\b|\bether\b|\beth\b', ('ethereum cryptocurrency', 'blockchain technology')),
    (r'\busdt\b|\btether\b|\bstablecoin', ('cryptocurrency trading', 'digital currency')),
    (r'\bgold\b|\bsilver\b', ('gold bullion', 'precious metals')),
    (r'\boil\b|\bbrent\b', ('oil industry', 'energy market')),
    (r'\bcrypto|blockchain|defi\b', ('cryptocurrency trading', 'blockchain technology')),
    (r'\binflation\b|\beconomy\b|\beconomic\b|\brate\b|\bbank', ('financial market', 'economy finance')),
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def _read(url, *, headers=None, limit=API_LIMIT, timeout=8):
    request = Request(url, headers={'User-Agent':UA, 'Accept':'application/json', **(headers or {})})
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Empty or oversized stock response')
    return data

def _key(provider):
    path = CONFIG/(provider+'-api-key')
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        key = path.read_text(encoding='utf-8').strip()
        if not 8 <= len(key) <= 256 or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            return None
        return key
    except (OSError, UnicodeError):
        return None

def _database(state=STATE):
    state = Path(state)
    if state.is_symlink() or not state.is_dir():
        raise ValueError('Unsafe stock state directory')
    path = state/'stock-images.sqlite3'
    if path.is_symlink():
        raise ValueError('Unsafe stock state database')
    con = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    con.executescript('''CREATE TABLE IF NOT EXISTS seen(
        provider TEXT NOT NULL, image_id TEXT NOT NULL, used_at REAL NOT NULL,
        PRIMARY KEY(provider,image_id));
        CREATE TABLE IF NOT EXISTS search_cache(
        provider TEXT NOT NULL, cache_key TEXT NOT NULL, fetched_at REAL NOT NULL, body TEXT NOT NULL,
        PRIMARY KEY(provider,cache_key));''')
    con.commit()
    return con

def queries(story):
    text = str(story.get('title_original','')).lower()
    matches = [terms for pattern, terms in TOPICS if re.search(pattern, text)]
    if not matches:
        if story.get('stock_category') == 'economy':
            return ['financial news', 'stock market']
        if story.get('stock_category') == 'crypto':
            return ['cryptocurrency', 'blockchain technology']
        return []
    # Mix the most specific event type with the asset or broader topic.
    selected = []
    for group in matches:
        for query in group:
            if query not in selected:
                selected.append(query)
            if len(selected) == 3:
                return selected
    return selected

def _safe_url(url, host, prefix='/'):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname == host
                and parts.port in (None,443) and not parts.username and not parts.password
                and parts.path.startswith(prefix) and not parts.fragment)
    except (TypeError, ValueError):
        return False

def _api(provider, query, key, con, now, *, bypass_cache=False):
    cache_key = hashlib.sha256(query.encode('utf-8')).hexdigest()
    cached = con.execute('SELECT fetched_at,body FROM search_cache WHERE provider=? AND cache_key=?',
                         (provider,cache_key)).fetchone()
    # Pixabay requires 24-hour caching. Pexels uses a shorter cache.
    lifetime = 86400 if provider == 'pixabay' else 21600
    if not bypass_cache and cached and 0 <= now-cached[0] < lifetime:
        return json.loads(cached[1])
    if provider == 'pexels':
        url = 'https://api.pexels.com/v1/search?' + urlencode({'query':query,'per_page':40,'orientation':'landscape'})
        raw = _read(url, headers={'Authorization':key})
    elif provider == 'pixabay':
        url = 'https://pixabay.com/api/?' + urlencode({'key':key,'q':query,'per_page':40,'image_type':'photo','safesearch':'true'})
        raw = _read(url)
    else:
        raise ValueError('Unknown stock provider')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid stock API response')
    # Store only results, never the request URL or API key.
    con.execute('INSERT OR REPLACE INTO search_cache VALUES(?,?,?,?)',
                (provider,cache_key,now,json.dumps(value,ensure_ascii=False)))
    con.commit()
    return value

def _candidates(provider, data):
    rows = data.get('photos',[]) if provider == 'pexels' else data.get('hits',[])
    if not isinstance(rows,list):
        return []
    result = []
    for row in rows[:40]:
        if not isinstance(row,dict) or type(row.get('id')) is not int or row['id'] <= 0:
            continue
        if provider == 'pexels':
            image = row.get('src',{}).get('large2x','') if isinstance(row.get('src'),dict) else ''
            page = row.get('url','')
            creator = row.get('photographer','')
            if not _safe_url(image,'images.pexels.com') or not _safe_url(page,'www.pexels.com','/photo/'):
                continue
        else:
            image, page, creator = row.get('largeImageURL',''),row.get('pageURL',''),row.get('user','')
            if not (_safe_url(image,'pixabay.com','/get/') or _safe_url(image,'cdn.pixabay.com','/photo/')):
                continue
            if not _safe_url(page,'pixabay.com','/'):
                continue
        if not isinstance(creator,str):
            continue
        creator = re.sub(r'\s+',' ',creator).strip()
        if not creator or len(creator)>100 or re.search(r'[<>\r\n]|https?://',creator):
            continue
        result.append({'provider':provider, 'id':str(row['id']), 'url':image,
                       'source_url':page, 'author':creator})
    return result

def collect(story, output_dir, *, origin, state=STATE, limit=7, provider_filter=None):
    """Fetch stock illustrations; no model calls or credentials in logs."""
    terms = queries(story)
    if not terms or limit <= 0:
        return []
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError('Unsafe stock output directory')
    limit = min(7, int(limit))
    providers = ['pexels']
    # Pixabay says its API is made for real human requests. Keep scheduled
    # use off unless the provider explicitly authorizes the intended workflow.
    if origin in {'admin_link','admin_direct'}:
        providers.append('pixabay')
    if provider_filter is not None:
        providers = [p for p in providers if p in provider_filter]
    now = time.time()
    deadline = time.monotonic()+35
    selected = []
    with closing(_database(state)) as con:
        con.execute('DELETE FROM seen WHERE used_at < ?', (now-HISTORY_DAYS*86400,))
        con.commit()
        seen = {(row[0],row[1]):row[2] for row in con.execute('SELECT provider,image_id,used_at FROM seen')}
        candidates = []
        for provider in providers:
            key = _key(provider)
            if not key:
                continue
            for query in terms[:2]:
                if time.monotonic() >= deadline:
                    break
                try:
                    data = _api(provider,query,key,con,now)
                    candidates.extend(_candidates(provider,data))
                except Exception as exc:
                    print('Stock image search unavailable:',provider,type(exc).__name__,flush=True)
                    break
        # Deduplicate across query results; favor images unused for 30 days,
        # then least-recently-used ones, in a different random order per run.
        unique = {(x['provider'],x['id']):x for x in candidates}
        candidates = list(unique.values())
        secrets.SystemRandom().shuffle(candidates)
        candidates.sort(key=lambda x:seen.get((x['provider'],x['id']),0))
        for item in candidates:
            if len(selected)>=limit or time.monotonic()>=deadline:
                break
            target = None
            try:
                raw = _read(item['url'], headers={'Accept':'image/jpeg,image/png,image/webp'},
                            limit=MAX_IMAGE, timeout=max(1,min(6,deadline-time.monotonic())))
                with Image.open(BytesIO(raw)) as img:
                    if img.width < 256 or img.height < 128 or img.width*img.height > 40_000_000:
                        continue
                    img.verify()
                with Image.open(BytesIO(raw)) as img:
                    clean = ImageOps.exif_transpose(img).convert('RGB')
                    clean.thumbnail((1920,1920), Image.Resampling.LANCZOS)
                    target = output_dir/('stock-'+str(len(selected))+'.jpg')
                    if target.exists() or target.is_symlink():
                        raise ValueError('Unsafe stock destination')
                    clean.save(target,format='JPEG',quality=92)
                    target.chmod(0o600)
                selected.append(dict(item,path=target,kind='illustrative'))
            except Exception:
                if target is not None and target.is_file() and not target.is_symlink():
                    target.unlink()
    return selected

def mark_used(items, *, state=STATE):
    if not items:
        return
    now = time.time()
    with closing(_database(state)) as con:
        for item in items:
            con.execute('INSERT OR REPLACE INTO seen VALUES(?,?,?)',
                        (item['provider'],item['id'],now))
        con.commit()
