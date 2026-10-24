"""Fixed official endpoints and existing gold/BTC parsers; unknown feeds fail closed."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from economic_calendar_data import Document
import global_metals_data as metals
from iran_gold_servix import load_key, clean_key
from risk_market_core import (ASSETS, SPOT, RiskError, UTC, NEW_YORK, canonical, capture_anchor, corroborate,
                              day, number, report_friday, stamp)

FRED={'vix':('VIXCLS','Index','Daily'), 'us10y':('DGS10','Percent','Daily'),
      'brent':('DCOILBRENTEU','Dollars per Barrel','Daily'),
      'dollar':('DTWEXBGS','Index Jan 2006=100','Daily'),'stress':('STLFSI4','Index','Weekly')}
CBOE={'vix':('VIX_History.csv','CLOSE')}
H15='https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series=bf17364827e38702b42a58cf8eaa3f78&lastobs=&from=&to=&filetype=csv&label=include&layout=seriescolumn&type=package'
EIA='https://www.eia.gov/dnav/pet/hist/RBRTED.htm'
FED='https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm'
STRESS_CSV='https://fred.stlouisfed.org/graph/fredgraph.csv?id=STLFSI4'
CATALOG='https://servix.cc/api/v1/assets/supported'
PRICES='https://servix.cc/api/v1/assets?'+urlencode({'codes':'GOLD_OUNCE_USD,BTC_USD'})
ALAN='https://alanchand.com/gold-price'
DOLAR='https://dolarchand.com/en/gold-silver'
PAPRIKA='https://api.coinpaprika.com/v1/tickers/btc-bitcoin'
SERVIX={'gold':('GOLD_OUNCE_USD','Gold Ounce / US Dollar'), 'btc':('BTC_USD','Bitcoin / US Dollar')}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def allowed(url):
    fixed={CATALOG,PRICES,ALAN,DOLAR,PAPRIKA,EIA,FED,H15,STRESS_CSV}
    fixed.update('https://fred.stlouisfed.org/data/'+s[0] for s in FRED.values())
    fixed.update('https://cdn-api.cboe.com/api/global/us_indices/daily_prices/'+file for file,_ in CBOE.values())
    return url in fixed


def fetch(url, folder, name, key=None):
    if not allowed(url) or bool(key)!=(url in {CATALOG,PRICES}):
        raise RiskError('Unreviewed risk source or authentication target.')
    headers={'User-Agent':'KianiExchange-RiskResearch/1.0','Accept-Encoding':'identity'}
    if key:
        headers['X-API-Key']=clean_key(key)
        headers['Accept']='application/json'
        headers['Cache-Control']='no-cache'
    try:
        deadline=time.monotonic()+35
        with build_opener(NoRedirect()).open(Request(url,headers=headers),timeout=15) as response:
            if response.status!=200 or response.url!=url:
                raise RiskError('Unexpected source response.')
            chunks=[];size=0
            while size<=2_000_000:
                if time.monotonic()>deadline:
                    raise RiskError('Source read time budget expired.')
                chunk=response.read1(min(65536,2_000_001-size))
                if not chunk:
                    break
                chunks.append(chunk);size+=len(chunk)
        raw=b''.join(chunks)
        if not raw or len(raw)>2_000_000:
            raise RiskError('Empty or oversized source response.')
        body=raw.decode('utf-8-sig')
        if key and key in body:
            raise RiskError('Source unexpectedly echoed authentication material.')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=folder/(name+'.body')
        if path.is_symlink() or path.exists():
            raise RiskError('Source evidence target already exists.')
        path.write_bytes(raw);path.chmod(0o600)
        return dict(text=body,sha256=hashlib.sha256(raw).hexdigest(),path=str(path),url=url,
                    retrieved_at=datetime.now(UTC).isoformat())
    except HTTPError as exc:
        raise RiskError('Risk source HTTP '+str(exc.code)) from None
    except RiskError:
        raise
    except Exception as exc:
        raise RiskError('Risk source unavailable: '+type(exc).__name__) from None


def quote(asset,provider,session,value,receipt,observed=None,**evidence):
    spec=ASSETS[asset]
    return dict(asset=asset,provider=provider,session_date=session,value=str(number(value)),
                unit=spec['unit'],basis=spec['basis'],originator=spec['origin'],final=True,
                observed_at=observed,retrieved_at=receipt['retrieved_at'],source_url=receipt['url'],
                response_sha256=receipt['sha256'],response_path=receipt['path'],**evidence)


def parse_fred(receipt,asset,wanted):
    series,unit,frequency=FRED[asset]
    root=Document(receipt['text']).root
    tables=list(root.nodes('table'))
    metadata={}
    for table in tables:
        if table.attrs.get('id')=='data-table-observations':
            continue
        for row in table.nodes('tr'):
            cells=[c for c in row.children if getattr(c,'tag','') in {'th','td'}]
            if len(cells)==2:
                label=cells[0].text().strip()
                if label in {'Series ID','Units','Frequency','Date Range'}:
                    if label in metadata:
                        raise RiskError('Repeated FRED series metadata.')
                    metadata[label]=cells[1].text().strip()
    if metadata.get('Series ID')!=series or metadata.get('Units')!=unit or not metadata.get('Frequency','').startswith(frequency):
        raise RiskError('FRED series identity, unit or daily frequency changed.')
    observations={}
    def put(d,v):
        day(d)
        if d in observations:
            raise RiskError('Repeated or ambiguous FRED observation date.')
        observations[d]=None if v=='.' else str(number(v))
    selected=[t for t in tables if t.attrs.get('id')=='data-table-observations']
    if len(selected)!=1:
        raise RiskError('FRED observation table is missing or repeated.')
    headers=[]
    for row in selected[0].nodes('tr'):
        cells=[c for c in row.children if getattr(c,'tag','') in {'th','td'}]
        text=[c.text().strip() for c in cells]
        if text==['DATE','VALUE']:
            headers.append(text)
        elif len(text)==2 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',text[0]):
            put(*text)
    if len(headers)!=1:
        raise RiskError('FRED observation headers changed.')
    extras=[n for n in root.nodes('div') if n.attrs.get('id')=='extra-rows']
    if len(extras)>1:
        raise RiskError('Repeated FRED extra-observation section.')
    if extras:
        for piece in extras[0].text().split('#'):
            piece=piece.strip()
            if not piece:
                continue
            matched=re.fullmatch(r'(\d{4}-\d{2}-\d{2})\|\s*(-?[0-9.]+)',piece)
            if not matched:
                raise RiskError('FRED extra-observation schema changed.')
            put(*matched.groups())
    dates=re.fullmatch(r'(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})',metadata.get('Date Range',''))
    if not dates or not observations or min(observations)!=dates[1] or max(observations)!=dates[2]:
        raise RiskError('FRED table coverage differs from its series metadata.')
    return [quote(asset,'fred',d,observations[d],receipt,series_id=series)
            for d in wanted if observations.get(d) is not None],max(observations)


def parse_cboe(receipt,asset,wanted):
    reader=csv.DictReader(io.StringIO(receipt['text']))
    expected=['DATE','OPEN','HIGH','LOW','CLOSE'] if asset=='vix' else ['DATE','SPX']
    if reader.fieldnames!=expected:
        raise RiskError('Cboe index headers changed.')
    rows={}
    for row in reader:
        d=datetime.strptime(row['DATE'],'%m/%d/%Y').date().isoformat()
        if d in rows:
            raise RiskError('Repeated Cboe close date.')
        value=number(row[CBOE[asset][1]])
        if asset=='vix' and d in wanted:
            lo,hi=number(row['LOW']),number(row['HIGH'])
            if not lo<=value<=hi or not lo<=number(row['OPEN'])<=hi:
                raise RiskError('Inconsistent Cboe OHLC observation.')
        rows[d]=str(value)
    return [quote(asset,'cboe',d,rows[d],receipt) for d in wanted if d in rows],max(rows)


def parse_h15(receipt,wanted):
    reader=csv.reader(io.StringIO(receipt['text']))
    metadata=[next(reader) for _ in range(6)]
    if ([r[0].strip() for r in metadata]!=['Series Description','Unit:','Multiplier:','Currency:','Unique Identifier:','Time Period'] or
            len(set(metadata[5]))!=len(metadata[5]) or metadata[5].count('RIFLGFCY10_N.B')!=1):
        raise RiskError('H.15 package identity or headers changed.')
    column=metadata[5].index('RIFLGFCY10_N.B')
    expected='Market yield on U.S. Treasury securities at 10-year constant maturity, quoted on investment basis'
    if (' '.join(metadata[0][column].split())!=expected or metadata[1][column]!='Percent:_Per_Year' or
            metadata[2][column]!='1' or metadata[4][column]!='H15/H15/RIFLGFCY10_N.B'):
        raise RiskError('H.15 exact 10-year constant-maturity definition changed.')
    rows={}
    for row in reader:
        if not row: continue
        if len(row)!=len(metadata[5]): raise RiskError('H.15 row length differs.')
        d=row[0];day(d)
        if d in rows: raise RiskError('Repeated H.15 observation date.')
        rows[d]=None if row[column] in {'','ND','NA','.'} else str(number(row[column]))
    return [quote('us10y','fed_h15',d,rows[d],receipt,series_id='RIFLGFCY10_N.B')
            for d in wanted if rows.get(d) is not None],max(rows)


def parse_eia(receipt,wanted):
    root=Document(receipt['text']).root
    if 'Europe Brent Spot Price FOB' not in root.text() or 'Dollars per Barrel' not in root.text():
        raise RiskError('EIA Brent spot identity changed.')
    rows={};months={m:i for i,m in enumerate(('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'),1)}
    for row in root.nodes('tr'):
        cells=[c for c in row.children if getattr(c,'tag','')=='td']
        if len(cells)!=6:
            continue
        label=' '.join(cells[0].text().split())
        m=re.fullmatch(r'(\d{4}) ([A-Z][a-z]{2})-\s*(\d{1,2}) to ([A-Z][a-z]{2})-\s*(\d{1,2})',label)
        if not m:
            continue
        start=datetime(int(m[1]),months[m[2]],int(m[3])).date()
        if start.weekday()!=0 or ((start+timedelta(days=4)).month,(start+timedelta(days=4)).day)!=(months[m[4]],int(m[5])):
            raise RiskError('EIA weekly table dates differ.')
        for i,cell in enumerate(cells[1:]):
            d=(start+timedelta(days=i)).isoformat();value=cell.text().strip()
            if d in rows:
                raise RiskError('Repeated EIA observation date.')
            rows[d]=None if value in {'','NA','--','-','W'} else str(number(value))
    valid={d:v for d,v in rows.items() if v is not None}
    if not valid:
        raise RiskError('EIA spot observations missing.')
    return [quote('brent','eia',d,valid[d],receipt) for d in wanted if d in valid],max(valid)


def parse_fed(receipt,wanted):
    root=Document(receipt['text']).root
    if 'Nominal Broad Dollar Index - Daily Index' not in root.text():
        raise RiskError('Federal Reserve nominal broad dollar identity changed.')
    rows={};months={m:i for i,m in enumerate(('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'),1)}
    for row in root.nodes('tr'):
        cells=[c for c in row.children if getattr(c,'tag','') in {'th','td'}]
        if len(cells)!=2:
            continue
        d,value=[c.text().strip() for c in cells]
        match=re.fullmatch(r'(\d{1,2})-([A-Z]{3})-(\d{2})',d)
        if not match:
            continue
        year=2000+int(match[3])
        d=datetime(year,months[match[2]],int(match[1])).date().isoformat()
        if d in rows:
            raise RiskError('Repeated Fed dollar observation date.')
        rows[d]=None if value in {'ND','NA','.'} else str(number(value))
    valid={d:v for d,v in rows.items() if v is not None}
    if not valid:
        raise RiskError('Fed broad dollar data missing.')
    return [quote('dollar','fed',d,valid[d],receipt) for d in wanted if d in valid],max(valid)


def parse_stress_csv(receipt,wanted):
    reader=csv.DictReader(io.StringIO(receipt['text']))
    if reader.fieldnames!=['observation_date','STLFSI4']:
        raise RiskError('STLFSI4 CSV headers changed.')
    rows={}
    for row in reader:
        d=row['observation_date'];day(d)
        if d in rows or day(d).weekday()!=4:
            raise RiskError('Repeated or non-Friday STLFSI4 date.')
        rows[d]=None if row['STLFSI4'] in {'','.'} else str(number(row['STLFSI4']))
    return [quote('stress','fred_csv',d,rows[d],receipt,series_id='STLFSI4')
            for d in wanted if rows.get(d) is not None],max(rows)


def public_sources(folder,friday=None):
    end=friday or report_friday().isoformat();previous=(day(end)-timedelta(days=28)).isoformat()
    wanted={(day(end)-timedelta(days=i)).isoformat() for i in range(29)};jobs={}
    for asset,(series,_,_) in FRED.items():
        jobs['fred_'+asset]=('https://fred.stlouisfed.org/data/'+series,lambda r,a=asset:parse_fred(r,a,wanted))
    for asset,(file,_) in CBOE.items():
        jobs['cboe_'+asset]=('https://cdn-api.cboe.com/api/global/us_indices/daily_prices/'+file,lambda r,a=asset:parse_cboe(r,a,wanted))
    jobs['fed_h15']=(H15,lambda r:parse_h15(r,wanted))
    jobs['eia_brent']=(EIA,lambda r:parse_eia(r,wanted))
    jobs['fed_dollar']=(FED,lambda r:parse_fed(r,wanted))
    jobs['fred_stress_csv']=(STRESS_CSV,lambda r:parse_stress_csv(r,wanted))
    observations=[];health={}
    def one(name,url,parser):
        receipt=fetch(url,folder,name);rows,latest=parser(receipt)
        return rows,dict(status='ok',latest_observation=latest,matched_dates=sorted({q['session_date'] for q in rows}),
                         response_sha256=receipt['sha256'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(one,name,*job):name for name,job in jobs.items()}
        for future in as_completed(futures):
            name=futures[future]
            try:
                rows,health[name]=future.result();observations.extend(rows)
            except Exception as exc:
                health[name]=dict(status='blocked',reason=str(exc) if isinstance(exc,RiskError) else type(exc).__name__)
    return observations,health


def servix_catalog(folder):
    receipt=fetch(CATALOG,folder,'servix_catalog',load_key())
    d=metals.json_data(receipt['text']);rows=d.get('assets') if isinstance(d,dict) else d
    if not isinstance(rows,list) or not all(isinstance(row,dict) and isinstance(row.get('code'),str) for row in rows):
        raise RiskError('Servix catalog schema changed.')
    if len({row['code'] for row in rows})!=len(rows):
        raise RiskError('Servix catalog has repeated instrument codes.')
    terms=('gold','bitcoin','btc','brent','crude','vix','volatility','dxy','dollar index','s&p','sp500','treasury','yield','spread','credit')
    fields=('code','labelEn','quoteUnit','businessTime','providerSupported','latestValueAvailable','qualityStatus','providers')
    return [dict((k,str(row[k]) if isinstance(row[k],Decimal) else row[k]) for k in fields if k in row)
            for row in rows if any(t in (row.get('code','')+' '+str(row.get('labelEn',''))).lower() for t in terms)]


def capture_spots(folder,*,probe=False):
    now=datetime.now(UTC);anchor=capture_anchor(now)
    if anchor is None and not probe:
        raise RiskError('Outside the Friday 17:00–17:15 New York spot-capture window.')
    session=(anchor or now).astimezone(NEW_YORK).date().isoformat()
    cat=fetch(CATALOG,folder,'servix_catalog',load_key());prices=fetch(PRICES,folder,'servix_prices',load_key())
    metadata=metals.json_data(cat['text']);metadata=metadata.get('assets') if isinstance(metadata,dict) else metadata
    current=metals.json_data(prices['text']);current=current.get('assets') if isinstance(current,dict) else current
    if not isinstance(metadata,list) or not isinstance(current,list):
        raise RiskError('Servix current/catalog schema changed.')
    quotes=[];health={}
    for asset,(code,label) in SERVIX.items():
        try:
            mm=[r for r in metadata if isinstance(r,dict) and r.get('code')==code]
            qq=[r for r in current if isinstance(r,dict) and r.get('code')==code]
            if len(mm)!=1 or len(qq)!=1:
                raise RiskError('Exact Servix instrument missing or repeated.')
            m,q=mm[0],qq[0]
            if (m.get('labelEn')!=label or q.get('labelEn')!=label or m.get('quoteUnit')!='USD' or
                    q.get('quoteUnit')!='USD' or m.get('providers')!=['SERVIX'] or m.get('providerSupported') is not True or
                    m.get('latestValueAvailable') is not True or m.get('stale') is not False or
                    m.get('availabilityStatus') not in {'FRESH','AVAILABLE'} or m.get('qualityStatus')!='ACCEPTED' or
                    m.get('qualityMessage') not in (None,'')):
                raise RiskError('Servix USD instrument quality/identity is not accepted.')
            value,mid,bid,ask=[number(q.get(k)) for k in ('value','midPrice','buyPrice','sellPrice')]
            if (value!=mid or value!=(bid+ask)/2 or bid>ask or (ask-bid)/value>Decimal('.005') or
                    number(m.get('latestValue'))!=value or stamp(m.get('businessTime'))!=stamp(q.get('businessTime'))):
                raise RiskError('Servix catalog/time/midpoint differs.')
            quotes.append(quote(asset,'servix',session,value,prices,stamp(q['businessTime']).isoformat(),
                                catalog_sha256=cat['sha256'],catalog_path=cat['path']))
            health['servix_'+asset]=dict(status='ok')
        except Exception as exc:
            health['servix_'+asset]=dict(status='blocked',reason=str(exc) if isinstance(exc,RiskError) else type(exc).__name__)
    for provider,url,parser in (('alanchand',ALAN,metals.parse_alan),('dolarchand',DOLAR,metals.parse_dolar_global)):
        try:
            receipt=fetch(url,folder,provider);board=parser(receipt['text'],now)['gold']
            quotes.append(quote('gold',provider,session,board['price'],receipt,board['updated_at']))
            health[provider]=dict(status='ok')
        except Exception as exc:
            health[provider]=dict(status='blocked',reason=type(exc).__name__)
    try:
        receipt=fetch(PAPRIKA,folder,'coinpaprika');row=metals.json_data(receipt['text'])
        if row.get('id')!='btc-bitcoin' or row.get('symbol')!='BTC' or row.get('is_active',True) is not True:
            raise RiskError('CoinPaprika exact BTC instrument changed.')
        quotes.append(quote('btc','coinpaprika',session,row['quotes']['USD']['price'],receipt,row['last_updated']))
        health['coinpaprika']=dict(status='ok')
    except Exception as exc:
        health['coinpaprika']=dict(status='blocked',reason=type(exc).__name__)
    endpoints={}
    for asset in SPOT:
        try:
            if probe:
                qq=[q for q in quotes if q['asset']==asset and -60<=(now-stamp(q['observed_at'])).total_seconds()<=900]
                servix=next((q for q in qq if q['provider']=='servix'),None)
                others=[q for q in qq if q['provider']!='servix' and servix and
                        abs(number(q['value'])/number(servix['value'])-1)*100<=Decimal('.5') and
                        abs((stamp(q['observed_at'])-stamp(servix['observed_at'])).total_seconds())<=600]
                if not servix or not others:
                    raise RiskError('No fresh agreeing current spot pair: '+asset)
                health[asset+'_agreement']=dict(status='ok',channels=['servix']+[q['provider'] for q in others],
                    probe_only=True,not_a_historical_endpoint=True)
            else:
                endpoints[asset]=corroborate([q for q in quotes if q['asset']==asset],asset,session,capture=True)
        except RiskError as exc:
            health[asset+'_agreement']=dict(status='blocked',reason=str(exc))
    return endpoints,health


def verify_evidence(endpoint,root):
    """Reparse saved official receipts; spot receipts retain immutable capture evidence."""
    root=Path(root).resolve()
    for q in endpoint['evidence']:
        path=Path(q['response_path'])
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size>2_000_000:
            raise RiskError('Source evidence is outside the private audit directory.')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=q['response_sha256']:
            raise RiskError('Original source response changed.')
        r=dict(text=raw.decode('utf-8-sig'),sha256=q['response_sha256'],url=q['source_url'],path=str(path),retrieved_at=q['retrieved_at'])
        a,p,d=q['asset'],q['provider'],q['session_date']
        if a in SPOT:
            if p=='servix':
                cp=Path(q['catalog_path'])
                if cp.is_symlink() or not cp.resolve().is_relative_to(root) or cp.stat().st_size>2_000_000 or hashlib.sha256(cp.read_bytes()).hexdigest()!=q['catalog_sha256']:
                    raise RiskError('Servix catalog evidence changed.')
                data=metals.json_data(r['text']);rows=data.get('assets') if isinstance(data,dict) else data
                matches=[row for row in rows if row.get('code')==SERVIX[a][0]]
                if len(matches)!=1 or number(matches[0]['value'])!=number(q['value']) or stamp(matches[0]['businessTime'])!=stamp(q['observed_at']):
                    raise RiskError('Saved Servix quote differs from its response.')
                expected=PRICES
            elif p=='coinpaprika':
                data=metals.json_data(r['text']);expected=PAPRIKA
                if data['id']!='btc-bitcoin' or number(data['quotes']['USD']['price'])!=number(q['value']) or stamp(data['last_updated'])!=stamp(q['observed_at']):
                    raise RiskError('Saved Bitcoin quote differs from its response.')
            else:
                parser,expected=(metals.parse_alan,ALAN) if p=='alanchand' else (metals.parse_dolar_global,DOLAR)
                row=parser(r['text'],stamp(q['retrieved_at']))['gold']
                if number(row['price'])!=number(q['value']) or stamp(row['updated_at'])!=stamp(q['observed_at']):
                    raise RiskError('Saved gold quote differs from its response.')
            if r['url']!=expected:
                raise RiskError('Saved spot URL differs from its provider.')
            continue
        if p=='fred':
            expected='https://fred.stlouisfed.org/data/'+FRED[a][0];parsed,_=parse_fred(r,a,{d})
        elif p=='cboe':
            expected='https://cdn-api.cboe.com/api/global/us_indices/daily_prices/'+CBOE[a][0];parsed,_=parse_cboe(r,a,{d})
        elif p=='eia': expected=EIA;parsed,_=parse_eia(r,{d})
        elif p=='fed': expected=FED;parsed,_=parse_fed(r,{d})
        elif p=='fred_csv': expected=STRESS_CSV;parsed,_=parse_stress_csv(r,{d})
        elif p=='fed_h15': expected=H15;parsed,_=parse_h15(r,{d})
        else: raise RiskError('Saved provider is not qualified.')
        if r['url']!=expected or len(parsed)!=1 or canonical(parsed[0])!=canonical(q):
            raise RiskError('Parsed source evidence differs from its saved quote.')
