"""Free-data dashboard: exact definitions, dated observations, no invented score."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from itertools import combinations
import json
import re
from zoneinfo import ZoneInfo

VERSION = 'risk-dashboard-free-v1'
METHOD = 'dated-observations-v1'
UTC = timezone.utc
TEHRAN = ZoneInfo('Asia/Tehran')
NEW_YORK = ZoneInfo('America/New_York')
ASSETS = {
    'gold': dict(name='طلای جهانی', short='طلا', unit='USD/troy_ounce', basis='friday_17ny_spot',
                 origin='fragmented_spot', providers=('servix','alanchand','dolarchand'), tolerance='0.5'),
    'brent': dict(name='نفت برنت نقدی', short='برنت نقدی', unit='USD/barrel', basis='eia_brent_europe_spot_daily',
                  origin='EIA', providers=('eia','fred'), tolerance='0.01'),
    'btc': dict(name='بیت‌کوین', short='بیت‌کوین', unit='USD/BTC', basis='friday_17ny_spot',
                origin='fragmented_spot', providers=('servix','coinpaprika'), tolerance='0.5'),
    'vix': dict(name='نوسان ضمنی سهام', short='VIX', unit='index_points', basis='cboe_vix_close',
                origin='CBOE', providers=('cboe','fred'), tolerance='0.01'),
    'dollar': dict(name='شاخص گسترده دلار فدرال رزرو', short='دلار گسترده', unit='index_points_2006_100',
                   basis='fed_nominal_broad_dollar_daily',origin='Federal_Reserve',providers=('fed','fred'),tolerance='0.0001'),
    'us10y': dict(name='بازده اوراق ۱۰ ساله', short='اوراق ۱۰ ساله', unit='percent', basis='fed_constant_maturity_10y_daily',
                  origin='Federal_Reserve', providers=('fed_h15','fred'), tolerance='0.01'),
    'stress': dict(name='تنش مالی سنت‌لوئیس', short='تنش مالی STLFSI4',unit='index_points',basis='stlfsi4_weekly',
                   origin='St_Louis_Fed',providers=('fred','fred_csv'),tolerance='0.0001'),
}
BOUNDS = {'gold':('100','50000'), 'brent':('0.01','1000'), 'btc':('10','10000000'),
          'vix':('0.01','200'), 'dollar':('1','500'),'us10y':('0.001','30'), 'stress':('-10','30')}
SPOT = {'gold','btc'}
MAX_LAG={'gold':0,'btc':0,'brent':7,'vix':4,'dollar':10,'us10y':4,'stress':14}


class RiskError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value):
    if isinstance(value, bool) or value is None:
        raise RiskError('Missing or invalid numeric observation.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RiskError('Invalid decimal observation.') from None
    if not result.is_finite():
        raise RiskError('Non-finite observation.')
    return result


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise RiskError('An original timezone-aware timestamp is required.') from None


def day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise RiskError('An exact ISO observation date is required.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RiskError('Invalid observation date.') from None


def report_friday(now=None):
    local=(now or datetime.now(UTC)).astimezone(NEW_YORK)
    end=local.date()-timedelta(days=(local.weekday()-4)%7)
    # Do not select today's unfinished Friday session.
    if local.weekday()==4 and local.hour<18:
        end-=timedelta(days=7)
    return end


def spot_anchor(friday):
    friday=day(friday) if isinstance(friday,str) else friday
    if friday.weekday()!=4:
        raise RiskError('Spot observations are anchored to Friday.')
    return datetime.combine(friday,datetime.min.time(),NEW_YORK).replace(hour=17).astimezone(UTC)


def capture_anchor(now=None):
    now=now or datetime.now(UTC)
    local=now.astimezone(NEW_YORK)
    if local.weekday()!=4:
        return None
    anchor=spot_anchor(local.date())
    return anchor if 0 <= (now-anchor).total_seconds() < 900 else None


def validate_quote(quote, asset, session, *, capture=False):
    spec=ASSETS[asset]
    if (quote.get('asset')!=asset or quote.get('provider') not in spec['providers'] or
            quote.get('unit')!=spec['unit'] or quote.get('basis')!=spec['basis'] or
            quote.get('session_date')!=session or quote.get('final') is not True or
            quote.get('originator')!=spec['origin']):
        raise RiskError('Unqualified provider or mismatched instrument/unit/session: '+asset)
    value=number(quote.get('value')); low,high=map(Decimal,BOUNDS[asset])
    if not low<=value<=high:
        raise RiskError('Observation is outside the reviewed sanity bounds: '+asset)
    if not re.fullmatch('[0-9a-f]{64}',str(quote.get('response_sha256',''))):
        raise RiskError('Original-response digest missing: '+asset)
    if not isinstance(quote.get('source_url'),str) or not quote['source_url'].startswith('https://'):
        raise RiskError('Original source URL missing: '+asset)
    fetched=stamp(quote.get('retrieved_at'))
    if fetched>datetime.now(UTC)+timedelta(seconds=60):
        raise RiskError('Source retrieval is future-dated.')
    if asset in SPOT:
        anchor=spot_anchor(session)
        original=stamp(quote.get('observed_at'))
        if original>fetched+timedelta(seconds=60):
            raise RiskError('Original spot observation is future-dated.')
        if not -900 <= (original-anchor).total_seconds() <= 600:
            raise RiskError('Spot quote does not match the Friday reference window: '+asset)
        if not 0 <= (fetched-anchor).total_seconds() < 900:
            raise RiskError('A later historical retrieval cannot masquerade as a captured spot quote.')
        if capture and not 0 <= (datetime.now(UTC)-anchor).total_seconds() < 900:
            raise RiskError('Spot capture window expired.')
    elif quote.get('observed_at') is not None:
        # Date-only official observations keep their actual precision; do not
        # manufacture midnight timestamps for them.
        stamp(quote['observed_at'])
    return value


def corroborate(quotes, asset, session, *, capture=False):
    day(session)
    good, rejected, repeated={},[],set()
    for quote in quotes:
        try:
            validate_quote(quote,asset,session,capture=capture)
            provider=quote['provider']
            if provider in good or provider in repeated:
                good.pop(provider,None)
                repeated.add(provider)
                raise RiskError('Repeated provider is not another verification source.')
            good[provider]=quote
        except RiskError as exc:
            rejected.append(str(exc))
    if len(good)<2:
        raise RiskError(asset+': fewer than two qualified channels for '+session)
    clusters=[]
    values=[good[p] for p in sorted(good)]
    for size in range(len(values),1,-1):
        for subset in combinations(values,size):
            prices=[number(q['value']) for q in subset]
            if asset in SPOT:
                gap=(max(prices)-min(prices))/min(prices)*100
                times=[stamp(q['observed_at']) for q in subset]
                agrees=('servix' in {q['provider'] for q in subset} and
                        gap<=number(ASSETS[asset]['tolerance']) and (max(times)-min(times)).total_seconds()<=600)
            else:
                # Exact published precision, not a market-price percentage band.
                precision=Decimal(ASSETS[asset]['tolerance'])
                agrees=len({p.quantize(precision,rounding=ROUND_HALF_UP) for p in prices})==1
                gap=max(prices)-min(prices)
            if agrees:
                clusters.append((subset,gap))
        if clusters:
            break
    if len(clusters)!=1:
        raise RiskError(asset+': no unique agreeing source cluster for '+session)
    selected,gap=clusters[0]
    if asset in SPOT:
        median=sorted(number(q['value']) for q in selected)[len(selected)//2]
        chosen=min(selected,key=lambda q:(abs(number(q['value'])-median),q['provider']))
    else:
        preferred={'vix':'cboe','us10y':'fed_h15'}
        chosen=next((q for q in selected if q['provider']==preferred.get(asset)),selected[0])
    return dict(asset=asset, session_date=session, value=chosen['value'], unit=chosen['unit'],basis=chosen['basis'],
                contract=chosen.get('contract'), channels=[q['provider'] for q in selected],
                evidence=list(selected), agreement_gap=str(gap), rejected=rejected,
                corroboration=('separate publishers; upstream independence unconfirmed' if asset in SPOT else
                    'two formats from the SAME publisher; consistency check only' if asset=='stress' else
                    'two delivery channels of one originating benchmark'))


def validate_endpoint(endpoint, asset, session):
    expected=corroborate(endpoint.get('evidence',[]),asset,session)
    if canonical(expected)!=canonical(endpoint):
        raise RiskError('Saved corroboration differs from its source evidence: '+asset)
    return expected


def compare(endpoints, friday):
    current=day(friday)
    if current.weekday()!=4 or current>report_friday():
        raise RiskError('A completed Friday reporting week is required.')
    rows=[]
    for asset,spec in ASSETS.items():
        observations=endpoints.get(asset,{})
        dates=sorted(d for d in observations if day(d)<=current and (current-day(d)).days<=MAX_LAG[asset])
        latest=dates[-1] if dates else None
        previous=(day(latest)-timedelta(days=7)).isoformat() if latest else None
        if not latest or previous not in observations:
            raise RiskError('Missing corroborated weekly endpoint: '+asset)
        old,new=observations[previous],observations[latest]
        validate_endpoint(old,asset,old['session_date']);validate_endpoint(new,asset,new['session_date'])
        a,b=number(old['value']),number(new['value'])
        absolute=b-a; change=None if asset=='stress' else str((b/a-1)*100)
        rows.append(dict(id=asset,name=spec['name'],value=str(b),previous_value=str(a),unit=spec['unit'],
                         observation_date=new['session_date'],previous_date=old['session_date'],
                         lag_days=(current-day(new['session_date'])).days,
                         change_pct=change,change_points=str(absolute),change_bps=str(absolute*100)
                         if asset=='us10y' else None,current=new,previous=old))
    result=dict(version=VERSION,method=METHOD,week_start=(current-timedelta(days=7)).isoformat(),week_end=current.isoformat(),
                rows=rows,all_verified=True,layout_sample=False)
    result['assessment']=assess(result)
    return result


def assess(snapshot):
    if {r.get('id') for r in snapshot.get('rows',[])}!=set(ASSETS) or len(snapshot['rows'])!=len(ASSETS):
        raise RiskError('All seven approved free-data inputs are required.')
    rows={r['id']:r for r in snapshot['rows']}
    up=lambda k:number(rows[k]['change_points'])>0
    down=lambda k:number(rows[k]['change_points'])<0
    stress=number(rows['stress']['value'])
    headline='آخرین داده‌های منتشرشده بازارها'
    observations=[('شاخص تنش مالی بالاتر از میانگین تاریخی است.' if stress>0 else
                   'شاخص تنش مالی پایین‌تر از میانگین تاریخی است.' if stress<0 else
                   'شاخص تنش مالی برابر میانگین تاریخی است.'),
                  'تاریخ داده‌ها متفاوت است؛ تغییر هر ردیف با هفت روز قبلِ همان مشاهده سنجیده می‌شود.',
                  'این گزارش احتمال بحران یا بازده آینده را محاسبه نمی‌کند.']
    return dict(method=METHOD,headline=headline,observations=observations,
                severity_score=None,crisis_probability=None)


def sample():
    """Clearly fictional design fixture; rejected by every publishing path."""
    pairs={'gold':('4200','4000'),'brent':('110','116'),'btc':('82000','81000'),
           'vix':('19','21'),'dollar':('122','121'),'us10y':('5.10','5.00'),'stress':('-.70','-.60')}
    end=report_friday();rows=[]
    for key,(a,b) in pairs.items():
        a,b=number(a),number(b); diff=b-a
        rows.append(dict(id=key,name=ASSETS[key]['name'],value=str(b),previous_value=str(a),unit=ASSETS[key]['unit'],
                         observation_date=end.isoformat(),previous_date=(end-timedelta(days=7)).isoformat(),lag_days=0,
                         change_pct=None if key=='stress' else str((b/a-1)*100),change_points=str(diff),
                         change_bps=str(diff*100) if key=='us10y' else None))
    result=dict(version=VERSION,method=METHOD,week_start=(end-timedelta(days=7)).isoformat(),
                week_end=end.isoformat(),rows=rows,all_verified=False,layout_sample=True)
    result['assessment']=assess(result)
    return result
