"""Verified five-market snapshots; point-in-time prices, never provider 7d changes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import hashlib
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from iran_gold_data import Document, GoldError, TEHRAN, UTC, number, stamp, parse_dolar
from iran_gold_quorum import parse_alanchand, quote_price, ALAN
from iran_gold_servix import NoRedirect, load_key, clean_key, WARNING

VERSION = 'weekly-toman-v1'
KINDS = {'btc': 'بیت‌کوین', 'emami': 'سکه امامی', 'gold18': 'طلای ۱۸ عیار',
         'usd': 'دلار آمریکا', 'eth': 'اتریوم'}
CODES = {'usd': ('USD_RLS', 'US Dollar / Iranian Rial', 'RLS', 'USD'),
         'btc': ('BTC_USD', 'Bitcoin / US Dollar', 'USD', 'BTC'),
         'eth': ('ETH_USD', 'Ethereum / US Dollar', 'USD', 'ETH'),
         'emami': ('SEKKEH_RLS', 'Emami Coin / Iranian Rial', 'RLS', 'SEKKEH'),
         'gold18': ('GOLD_18_RLS', '18K Gold / Iranian Rial', 'RLS', 'GOLD_18')}
BASE = 'https://servix.cc/api/v1/'
CATALOG = BASE+'assets/supported'
CURRENT = BASE+'assets?'+urlencode({'codes': ','.join(s[0] for s in CODES.values())})
DOLAR = 'https://dolarchand.com/en'
DOLAR_GOLD = 'https://dolarchand.com/en/gold-silver'
PAPRIKA = {'btc': 'https://api.coinpaprika.com/v1/tickers/btc-bitcoin',
           'eth': 'https://api.coinpaprika.com/v1/tickers/eth-ethereum'}
URLS = {CATALOG, CURRENT, DOLAR, DOLAR_GOLD, ALAN, *PAPRIKA.values()}
META = ('code','labelEn','baseCode','quoteUnit','businessTime','latestValue','providers',
        'providerSupported','latestValueAvailable','availabilityStatus','stale','qualityStatus','qualityMessage')
BOUNDS = {'usd': (10000, 2000000), 'btc': (1000, 2000000), 'eth': (10, 100000),
          'emami': (80000000,600000000), 'gold18': (8000000,60000000)}
SKEW = 600


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fetch(url, key=None):
    if url not in URLS or bool(key) != url.startswith(BASE):
        raise GoldError('Unreviewed weekly-price endpoint or authentication target.')
    headers={'User-Agent':'KianiExchange-WeeklyComparison/1.0', 'Accept':'application/json,text/html',
             'Accept-Encoding':'identity','Cache-Control':'no-cache'}
    if key:
        headers['X-API-Key']=clean_key(key)
    try:
        deadline=time.monotonic()+30
        with build_opener(NoRedirect()).open(Request(url,headers=headers),timeout=12) as response:
            if response.status!=200 or response.url!=url:
                raise GoldError('Unexpected weekly-price source response.')
            chunks=[]; size=0
            while size<=2_000_000:
                if time.monotonic()>deadline:
                    raise GoldError('Weekly-price source exceeded its time budget.')
                chunk=response.read1(min(65536,2_000_001-size))
                if not chunk: break
                chunks.append(chunk); size+=len(chunk)
        raw=b''.join(chunks)
        if not raw or len(raw)>2_000_000:
            raise GoldError('Weekly-price source is empty or oversized.')
        return raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
    except HTTPError as exc:
        raise GoldError('Weekly-price source HTTP '+str(exc.code)) from None
    except GoldError: raise
    except Exception:
        raise GoldError('Weekly-price source connection or parsing unavailable.') from None


def decode(raw):
    def invalid(_): raise GoldError('Non-finite source number.')
    return json.loads(raw,parse_float=Decimal,parse_constant=invalid)


def observed(moment, now, anchor=None):
    moment=stamp(moment)
    age=(now.astimezone(UTC)-moment).total_seconds()
    if not -60<=age<=900 or moment.astimezone(TEHRAN).date()!=now.astimezone(TEHRAN).date():
        raise GoldError('Weekly source observation is stale or future-dated.')
    if anchor is not None and not -600<=(moment-anchor).total_seconds()<=120:
        raise GoldError('Source observation is outside the common valuation window.')
    return moment


def servix(catalog, current, catalog_hash, current_hash, now):
    if not isinstance(catalog,dict) or not isinstance(catalog.get('assets'),list) or not isinstance(current,list):
        raise GoldError('Servix weekly quote schema changed.')
    known={s[0] for s in CODES.values()}; metas={}; values={}
    for row in catalog['assets']:
        if not isinstance(row,dict): raise GoldError('Malformed Servix catalog row.')
        if row.get('code') in known:
            if row['code'] in metas: raise GoldError('Duplicate Servix catalog instrument.')
            metas[row['code']]=row
    for row in current:
        if not isinstance(row,dict) or row.get('code') not in known or row['code'] in values:
            raise GoldError('Unexpected or repeated Servix weekly quote.')
        values[row['code']]=row
    result={}
    for asset,spec in CODES.items():
        code,label,unit,_=spec; m=metas.get(code,{}); r=values.get(code,{})
        if (m.get('labelEn')!=label or r.get('labelEn')!=label or m.get('quoteUnit')!=unit or
                r.get('quoteUnit')!=unit or m.get('providers')!=['SERVIX'] or
                m.get('providerSupported') is not True or m.get('latestValueAvailable') is not True or
                m.get('availabilityStatus') not in {'FRESH','AVAILABLE'} or m.get('stale') is not False):
            raise GoldError('Servix exact weekly instrument/unit/availability differs: '+asset)
        quality,message=m.get('qualityStatus'),m.get('qualityMessage')
        warning=(quality=='ACCEPTED_WITH_WARNINGS' and asset not in {'btc','eth'} and
                 isinstance(message,str) and WARNING.fullmatch(message))
        if not warning and (quality!='ACCEPTED' or message not in (None,'')):
            raise GoldError('Servix weekly quality is not reviewed: '+asset)
        updated=observed(r.get('businessTime'),now)
        if updated!=stamp(m.get('businessTime')):
            raise GoldError('Servix catalog/quote observation mismatch.')
        value,mid,bid,ask=[number(r.get(k)) for k in ('value','midPrice','buyPrice','sellPrice')]
        if value!=mid or value!=number(m.get('latestValue')) or bid>ask or (bid+ask)/2!=mid:
            raise GoldError('Servix weekly sides and midpoint disagree.')
        if (ask-bid)/mid>Decimal('.01'):
            raise GoldError('Servix weekly spread exceeds one percent.')
        price=mid/10 if unit=='RLS' else mid
        lo,hi=BOUNDS[asset]
        if not lo<=price<=hi: raise GoldError('Servix weekly value outside conservative bounds.')
        result[asset]=dict(price=str(price),unit='toman' if unit=='RLS' else 'USD',
            updated_at=updated.isoformat(),code=code,original_value=str(value),
            bid_original=str(bid),ask_original=str(ask),catalog_record={k:str(m[k]) if k=='latestValue' else m.get(k) for k in META},
            catalog_hash=catalog_hash,page_hash=current_hash,source_url=CURRENT,
            quality_status=quality,quality_message=message,basis='midpoint')
    return result


def hydration(html):
    dec=json.JSONDecoder(); chunks=[]
    for m in re.finditer(r'self\.__next_f\.push\(',html):
        try: value,_=dec.raw_decode(html[m.end():].lstrip())
        except ValueError: continue
        if isinstance(value,list) and len(value)==2 and isinstance(value[1],str): chunks.append(value[1])
    return ''.join(chunks)


def dollar(html, page_hash, now):
    text=Document(html).root.text(); stream=hydration(html)
    if 'prices in Toman' not in text: raise GoldError('Dollar publisher does not declare toman.')
    times=set(re.findall(r'"initialIso"\s*:\s*"([^"\n]+)"',stream))
    if len(times)!=1: raise GoldError('Dollar publisher has no unique original board timestamp.')
    updated=observed(next(iter(times)),now)
    visible_time=re.search(r'Last updated ([A-Za-z]{3} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M)',text)
    if not visible_time or datetime.strptime(visible_time[1],'%b %d, %Y, %I:%M %p')!=updated.replace(tzinfo=None,second=0,microsecond=0):
        raise GoldError('Dollar visible and structured timestamps disagree.')
    maps=[]; dec=json.JSONDecoder()
    for m in re.finditer(r'"rates"\s*:',stream):
        try: value,_=dec.raw_decode(stream[m.end():].lstrip())
        except ValueError: continue
        if isinstance(value,dict) and {'USD','EUR','TRY'}<=set(value): maps.append(value)
    rows=[]
    for tr in Document(html).root.nodes('tr'):
        cells=[c.text() for c in tr.children if getattr(c,'tag','')=='td']
        if cells and cells[0]=='US Dollar': rows.append(cells)
    if len(maps)!=1 or len(rows)!=1 or len(rows[0])<3:
        raise GoldError('Dollar cash quote is missing or ambiguous.')
    r=maps[0]['USD']; bid,ask=number(r.get('buy')),number(r.get('sell'))
    if bid>ask or (ask-bid)/((bid+ask)/2)>Decimal('.02') or number(r.get('priceUsd'))!=1:
        raise GoldError('Dollar cash sides, spread or USD orientation are invalid.')
    if number(rows[0][1])!=bid or number(rows[0][2])!=ask:
        raise GoldError('Dollar visible and structured buy/sell quotes differ.')
    return dict(price=str((bid+ask)/2),bid=str(bid),ask=str(ask),unit='toman',
                updated_at=updated.isoformat(),page_hash=page_hash,source_url=DOLAR,basis='midpoint')


def crypto(asset, raw, page_hash, now):
    r=decode(raw); code={'btc':('btc-bitcoin','BTC'),'eth':('eth-ethereum','ETH')}[asset]
    if r.get('id')!=code[0] or r.get('symbol')!=code[1] or not isinstance(r.get('quotes'),dict):
        raise GoldError('CoinPaprika exact asset differs.')
    usd=r['quotes'].get('USD',{}); price=number(usd.get('price'))
    lo,hi=BOUNDS[asset]
    if not lo<=price<=hi or number(usd.get('volume_24h'))<Decimal('1000000'):
        raise GoldError('CoinPaprika price or liquidity is invalid.')
    return dict(price=str(price),unit='USD',updated_at=observed(r.get('last_updated'),now).isoformat(),
                source_url=PAPRIKA[asset],page_hash=page_hash,basis='aggregate_usd_spot',coin_id=code[0])


def cluster(quotes, limit=Decimal('1')):
    groups=[]
    for size in range(2,len(quotes)+1):
        for names in combinations(sorted(quotes),size):
            prices=[number(quotes[n]['price']) for n in names]; low,high=min(prices),max(prices)
            gap=(high-low)/((high+low)/2)*100
            if gap<=limit: groups.append((names,gap))
    if not groups: raise GoldError('Fewer than two publishers agree on a weekly price.')
    largest=max(len(g[0]) for g in groups); groups=[g for g in groups if len(g[0])==largest]
    if len(groups)!=1: raise GoldError('Weekly price consensus is ambiguous.')
    names,gap=groups[0]; ordered=sorted(number(quotes[n]['price']) for n in names)
    middle=(ordered[(len(ordered)-1)//2]+ordered[len(ordered)//2])/2
    selected=min(names,key=lambda n:(abs(number(quotes[n]['price'])-middle),n))
    return names,selected,gap


def compute(providers, moment, anchor=None):
    """Recompute from retained original evidence, including after seven days."""
    if set(providers)-{'servix','alanchand','dolarchand','coinpaprika'} or 'servix' not in providers:
        raise GoldError('Unexpected weekly publisher registry.')
    rows=[]; all_times=[]
    for asset,name in KINDS.items():
        candidates={}
        for source,board in providers.items():
            if asset not in board: continue
            q=board[asset]; price=number(q.get('price'))
            if not re.fullmatch('[0-9a-f]{64}',q.get('page_hash','')):
                raise GoldError('Missing original weekly source evidence hash.')
            observed(q.get('updated_at'),moment,anchor)
            if source=='servix':
                # Rebuild the exact current/catalog contract from stored original fields.
                v=number(q['original_value'])
                # Validate all five together below; never accept a relabeled unit.
                unit='USD' if asset in {'btc','eth'} else 'toman'
                if q['unit']!=unit or price!=(v if unit=='USD' else v/10) or q.get('source_url')!=CURRENT:
                    raise GoldError('Servix weekly conversion/source changed.')
            elif source in {'alanchand','dolarchand'} and asset in {'gold18','emami'}:
                if quote_price(source,asset,q,moment)!=price: raise GoldError('Gold quote differs.')
            elif source=='dolarchand' and asset=='usd':
                bid,ask=number(q['bid']),number(q['ask'])
                if q.get('source_url')!=DOLAR or q.get('unit')!='toman' or bid>ask or (bid+ask)/2!=price or (ask-bid)/price>Decimal('.02'):
                    raise GoldError('Cash USD evidence changed.')
            elif source=='coinpaprika' and asset in {'btc','eth'}:
                if q.get('source_url')!=PAPRIKA[asset] or q.get('unit')!='USD' or q.get('coin_id')!=PAPRIKA[asset].rsplit('/',1)[1]:
                    raise GoldError('Crypto exact source/unit changed.')
            else: raise GoldError('Unexpected asset/source pairing.')
            if not BOUNDS[asset][0]<=price<=BOUNDS[asset][1]: raise GoldError('Weekly source price is out of bounds.')
            candidates[source]=q
        names,selected,gap=cluster(candidates)
        if asset in {'usd','btc','eth'} and 'servix' not in names:
            raise GoldError('Dollar/crypto comparisons require a fresh original Servix observation.')
        times=[stamp(candidates[n]['updated_at']) for n in names]; all_times+=times
        rows.append(dict(id=asset,name=name,price=str(number(candidates[selected]['price'])),
            unit='USD' if asset in {'btc','eth'} else 'toman',sources=list(names),selected_source=selected,
            agreement_pct=str(gap.quantize(Decimal('.0001'))),
            observation_start=min(times).isoformat(),observation_end=max(times).isoformat()))
    # Validate the retained Servix batch with its original metadata, not fetch time.
    saved=providers['servix']; cat=[]; current=[]
    if set(saved)!=set(CODES): raise GoldError('Missing exact Servix weekly instruments.')
    for asset,q in saved.items():
        cat.append(q['catalog_record'])
        current.append(dict(code=q['code'],labelEn=q['catalog_record']['labelEn'],quoteUnit=q['catalog_record']['quoteUnit'],
            businessTime=q['updated_at'],value=q['original_value'],midPrice=q['original_value'],
            buyPrice=q['bid_original'],sellPrice=q['ask_original']))
    rebuilt=servix({'assets':cat},current,next(iter(saved.values()))['catalog_hash'],next(iter(saved.values()))['page_hash'],moment)
    if canonical(rebuilt)!=canonical(saved): raise GoldError('Servix evidence does not reproduce the saved quotes.')
    if (max(all_times)-min(all_times)).total_seconds()>SKEW:
        raise GoldError('Market observations are more than ten minutes apart.')
    dollar_price=number(next(r for r in rows if r['id']=='usd')['price'])
    for row in rows:
        if row['id'] in {'btc','eth'}:
            row['usd_price']=row['price']; row['price']=str(number(row['price'])*dollar_price)
            row['unit']='toman'; row['conversion']='asset_USD_times_same_snapshot_USD_toman'
        else: row['conversion']='rial_divided_by_10' if row['selected_source']=='servix' else 'published_toman'
    return rows


def collect(anchor=None):
    key=load_key()
    jobs={'servix_catalog':(CATALOG,key),'servix_prices':(CURRENT,key),
          'alanchand':(ALAN,None),'dolarchand':(DOLAR_GOLD,None),'dollar':(DOLAR,None),
          'btc':(PAPRIKA['btc'],None),'eth':(PAPRIKA['eth'],None)}
    raw={}; health={}
    def one(item):
        name,(url,auth)=item
        try: return name,fetch(url,auth),None
        except GoldError as exc: return name,None,str(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:
        for name,result,error in pool.map(one,jobs.items()):
            health[name]=dict(status='blocked' if error else 'ok',**({'reason':error} if error else {}))
            if result: raw[name]=result
    now=datetime.now(UTC); providers={}
    snapshot=dict(version=VERSION,status='blocked',generated_at=now.isoformat(),timezone='Asia/Tehran',
                  anchor=anchor.isoformat() if anchor else None,providers=providers,health=health,rows=[])
    try:
        for required in ('servix_catalog','servix_prices','dollar','btc','eth'):
            if required not in raw: raise GoldError('Required weekly source unavailable: '+required)
        catalog,ch=raw['servix_catalog']; current,ph=raw['servix_prices']
        providers['servix']=servix(decode(catalog),decode(current),ch,ph,now)
        providers['dolarchand']={'usd':dollar(*raw['dollar'],now)}
        for source,parser in [('alanchand',parse_alanchand),('dolarchand',parse_dolar)]:
            if source not in raw: continue
            try:
                html,page_hash=raw[source]; quotes=parser(html,now)
                for asset in ('gold18','emami'): observed(quotes[asset]['updated_at'],now,anchor)
                providers.setdefault(source,{}).update({a:dict(quotes[a],page_hash=page_hash) for a in ('gold18','emami')})
            except GoldError as exc: health[source]=dict(status='blocked',reason=str(exc))
        providers['coinpaprika']={a:crypto(a,*raw[a],now) for a in ('btc','eth')}
        snapshot['rows']=compute(providers,now,anchor)
        snapshot['status']='verified'
        validate(snapshot,live=True,now=now)
    except (GoldError,KeyError,TypeError,ValueError) as exc:
        snapshot['reason']=str(exc) if isinstance(exc,GoldError) else 'Incomplete weekly source contract.'
    return snapshot


def validate(snapshot, *, live=False, now=None):
    if (snapshot.get('layout_sample') or snapshot.get('status')!='verified' or
            snapshot.get('version')!=VERSION or snapshot.get('timezone')!='Asia/Tehran'):
        raise GoldError('Only verified original weekly snapshots may enter history.')
    generated=stamp(snapshot['generated_at']); anchor=stamp(snapshot['anchor']) if snapshot.get('anchor') else None
    if live and not -5<=((now or datetime.now(UTC))-generated).total_seconds()<=180:
        raise GoldError('Weekly source preflight expired.')
    expected=compute(snapshot['providers'],generated,anchor)
    if canonical(expected)!=canonical(snapshot['rows']): raise GoldError('Weekly prices differ from retained source evidence.')
    if anchor and not 0<=(generated-anchor).total_seconds()<=900:
        raise GoldError('Snapshot was not collected in its exact daily valuation window.')
    return expected


def compare(previous, current):
    validate(previous); validate(current)
    start,end=stamp(previous['anchor']),stamp(current['anchor'])
    if end-start!=timedelta(days=7): raise GoldError('A complete matching seven-day baseline is required.')
    if start.astimezone(TEHRAN).weekday()!=3 or end.astimezone(TEHRAN).hour!=20 or end.astimezone(TEHRAN).minute!=0:
        raise GoldError('Weekly comparison endpoints are not Thursday 20:00 Tehran.')
    before={r['id']:r for r in previous['rows']}; rows=[]
    for row in current['rows']:
        old=before[row['id']]
        # Require like-for-like source-time ranges, not a morning baseline and evening close.
        for field in ('observation_start','observation_end'):
            if abs((stamp(row[field])-stamp(old[field])-timedelta(days=7)).total_seconds())>300:
                raise GoldError('Weekly market observation times do not match within five minutes.')
        a,b=number(old['price']),number(row['price']); change=(b/a-1)*100
        rows.append(dict(id=row['id'],name=row['name'],start_price=str(a),end_price=str(b),
            change_pct=str(change),display_pct=str(change.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
            sources_start=old['sources'],sources_end=row['sources']))
    rows.sort(key=lambda r:(-Decimal(r['change_pct']),r['id']))
    return dict(version=VERSION,status='verified',timezone='Asia/Tehran',unit='toman',
                window_start=start.isoformat(),window_end=end.isoformat(),
                previous_hash=digest(previous),current_hash=digest(current),rows=rows)
