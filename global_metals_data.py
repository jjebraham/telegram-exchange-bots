"""USD/troy-ounce metals: original Servix observation plus a matching publisher."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from itertools import combinations
import hashlib
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from iran_gold_data import Document, GoldError, UTC, fresh, number, stamp, parse_dolar
from iran_gold_quorum import ALAN, parse_alanchand
from iran_gold_servix import BASE, META_FIELDS, NoRedirect, clean_key, load_key

VERSION = 'global-metals-v1'
SPEC = {
    'gold': ('اونس طلا', 'GOLD_OUNCE_USD', 'انس طلا', 'GOLD_OUNCE', 'Gold Ounce (Global)', 'Gold Ounce / US Dollar', 500, 20000),
    'silver': ('اونس نقره', 'SILVER_OUNCE_USD', 'انس نقره', 'SILVER_OUNCE', 'Silver Ounce (Global)', 'Silver Ounce / US Dollar', 1, 500),
}
URLS = {'alanchand': ALAN, 'dolarchand': 'https://dolarchand.com/en/gold-silver',
        'servix': BASE + 'assets?' + urlencode({'codes': ','.join(s[1] for s in SPEC.values())})}
CATALOG = BASE + 'assets/supported'
LIMIT = Decimal('0.5')
MAX_SKEW = 600


def fetch(url, key=None):
    if url not in {*URLS.values(), CATALOG} or bool(key) != url.startswith(BASE):
        raise GoldError('Unreviewed global-metals endpoint or authentication target.')
    headers = {'User-Agent': 'KianiExchange-GlobalMetals/1.0', 'Accept': 'application/json,text/html',
               'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'}
    if key:
        headers['X-API-Key'] = clean_key(key)
    try:
        deadline = time.monotonic() + 30
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=12) as response:
            if response.status != 200 or response.url != url:
                raise GoldError('Unexpected global-metals response.')
            chunks, size = [], 0
            while size <= 2_000_000:
                if time.monotonic() > deadline:
                    raise GoldError('Global-metals source time budget exceeded.')
                chunk = response.read1(min(65536, 2_000_001-size))
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
        body = b''.join(chunks)
        if not body or len(body) > 2_000_000:
            raise GoldError('Global-metals source is empty or oversized.')
        return body.decode('utf-8'), hashlib.sha256(body).hexdigest()
    except HTTPError as exc:
        raise GoldError('Global-metals source HTTP ' + str(exc.code)) from None
    except GoldError:
        raise
    except Exception:
        # Never include a URL, header, key or raw remote error in source failures.
        raise GoldError('Global-metals source connection/parsing unavailable.') from None


def json_data(raw):
    def invalid(_):
        raise GoldError('Global-metals JSON contains a non-finite value.')
    return json.loads(raw, parse_float=Decimal, parse_constant=invalid)


def parse_alan(html, now):
    # Reuse the already-reviewed Persian/Gregorian/weekday/clock/offset checks.
    dated = parse_alanchand(html, now)
    updated = next(iter(dated.values()))['updated_at']
    lists = [json_data(s) for s in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.S)]
    lists = [v for v in lists if isinstance(v, dict) and v.get('@type') == 'ItemList']
    if len(lists) != 1:
        raise GoldError('Alanchand global instrument list is ambiguous.')
    offers, visible = {}, {}
    for entry in lists[0].get('itemListElement', []):
        p = entry.get('item', {})
        if p.get('name') in {s[2] for s in SPEC.values()}:
            if p['name'] in offers:
                raise GoldError('Duplicate Alanchand global instrument.')
            offers[p['name']] = p.get('offers', {})
    for table in Document(html).root.nodes('table'):
        if not table.has('goldTbl'):
            continue
        for row in table.nodes('tr'):
            cells = [x for x in row.children if getattr(x, 'tag', '') == 'td']
            if cells and cells[0].text() in {s[2] for s in SPEC.values()}:
                name = cells[0].text()
                if name in visible or len(cells) != 4:
                    raise GoldError('Alanchand global row is ambiguous.')
                from iran_gold_data import DIGITS
                match = re.fullmatch(r'([0-9,.]+)\$\s*[+-]?[0-9.]+%', cells[1].text().translate(DIGITS))
                if not match:
                    raise GoldError('Alanchand global USD row changed.')
                visible[name] = number(match[1])
    result = {}
    for asset, spec in SPEC.items():
        offer = offers.get(spec[2], {})
        if offer.get('priceCurrency') != 'USD' or spec[2] not in visible:
            raise GoldError('Alanchand global USD instrument is missing.')
        price = number(offer.get('price'))
        if price != visible[spec[2]] or not 0 <= (stamp(offer.get('priceValidUntil'))-stamp(updated)).total_seconds() <= 7200:
            raise GoldError('Alanchand global visible/structured price or date differs.')
        result[asset] = dict(price=str(price), unit='USD/troy_ounce', updated_at=updated,
            source_url=ALAN, basis='published_spot', visible_usd=str(visible[spec[2]]),
            structured_usd=str(price), expiry=offer['priceValidUntil'])
    return result


def hydration(html):
    decoder, chunks = json.JSONDecoder(), []
    for m in re.finditer(r'self\.__next_f\.push\(', html):
        try:
            value, _ = decoder.raw_decode(html[m.end():].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
            chunks.append(value[1])
    return ''.join(chunks), decoder


def parse_dolar_global(html, now):
    updated = next(iter(parse_dolar(html, now).values()))['updated_at']
    stream, decoder = hydration(html)
    codes = {s[3] for s in SPEC.values()}
    maps, instruments = [], []
    for m in re.finditer(r'"rates"\s*:', stream):
        obj, _ = decoder.raw_decode(stream[m.end():].lstrip())
        if isinstance(obj, dict) and codes <= set(obj):
            maps.append(obj)
    for m in re.finditer(r'"instruments"\s*:', stream):
        obj, _ = decoder.raw_decode(stream[m.end():].lstrip())
        if isinstance(obj, list) and codes <= {x.get('code') for x in obj if isinstance(x, dict)}:
            instruments.append(obj)
    if len(maps) != 1 or len(instruments) != 1:
        raise GoldError('DolarChand global maps are missing/ambiguous.')
    definitions = {s[3]: [x for x in instruments[0] if x.get('code') == s[3]] for s in SPEC.values()}
    visible = {}
    for row in Document(html).root.nodes('tr'):
        cells = [x.text() for x in row.children if getattr(x, 'tag', '') == 'td']
        if cells and cells[0] in {s[4] for s in SPEC.values()}:
            if cells[0] in visible or len(cells) < 3:
                raise GoldError('Duplicate/incomplete DolarChand global row.')
            visible[cells[0]] = cells
    result = {}
    for asset, spec in SPEC.items():
        defs, quote, shown = definitions[spec[3]], maps[0][spec[3]], visible.get(spec[4], [])
        if len(defs) != 1 or defs[0].get('unit') != 'per ounce' or defs[0].get('name') != spec[4]:
            raise GoldError('DolarChand global instrument/volume changed.')
        bid, ask, usd = [number(quote.get(k)) for k in ('buy', 'sell', 'priceUsd')]
        if len(shown) < 3 or number(shown[1]) != bid or number(shown[2]) != ask or (bid+ask)/2 != usd:
            raise GoldError('DolarChand global USD field/sides/visible prices disagree.')
        result[asset] = dict(price=str(usd), bid=str(bid), ask=str(ask), usd_field=str(usd),
            unit='USD/troy_ounce', updated_at=updated, source_url=URLS['dolarchand'], basis='midpoint')
    return result


def parse_servix(catalog, current, now):
    if not isinstance(catalog, dict) or not isinstance(catalog.get('assets'), list) or not isinstance(current, list):
        raise GoldError('Servix global-metals schema changed.')
    if len(current) != 2 or {x.get('code') for x in current if isinstance(x,dict)} != {s[1] for s in SPEC.values()}:
        raise GoldError('Servix current global instruments are unexpected/repeated.')
    result = {}
    for asset, spec in SPEC.items():
        metas = [x for x in catalog['assets'] if isinstance(x, dict) and x.get('code') == spec[1]]
        rows = [x for x in current if isinstance(x, dict) and x.get('code') == spec[1]]
        if len(metas) != 1 or len(rows) != 1:
            raise GoldError('Servix exact global instrument is missing/repeated.')
        m, q = metas[0], rows[0]
        if (m.get('quoteUnit') != 'USD' or q.get('quoteUnit') != 'USD' or
                m.get('labelEn') != spec[5] or q.get('labelEn') != spec[5] or
                m.get('providers') != ['SERVIX'] or m.get('providerSupported') is not True or
                m.get('latestValueAvailable') is not True or m.get('stale') is not False or
                m.get('availabilityStatus') not in {'FRESH', 'AVAILABLE'} or
                m.get('qualityStatus') != 'ACCEPTED' or m.get('qualityMessage') not in (None, '')):
            raise GoldError('Servix global USD instrument quality/coverage is not accepted.')
        values = [number(q.get(k)) for k in ('value', 'midPrice', 'buyPrice', 'sellPrice')]
        value, mid, bid, ask = values
        updated = stamp(q.get('businessTime'))
        if updated != stamp(m.get('businessTime')) or value != number(m.get('latestValue')) or value != mid or value != (bid+ask)/2:
            raise GoldError('Servix global quote/catalog observation or midpoint differs.')
        fresh(updated, now)
        result[asset] = dict(price=str(value), bid=str(bid), ask=str(ask), unit='USD/troy_ounce',
            updated_at=updated.isoformat(), source_url=URLS['servix'], basis='midpoint',
            catalog_record={k: str(m[k]) if isinstance(m.get(k), Decimal) else m.get(k) for k in (*META_FIELDS, 'labelEn')},
            current_record={k: str(q[k]) if isinstance(q.get(k), Decimal) else q.get(k) for k in
                ('code','labelEn','quoteUnit','businessTime','value','midPrice','buyPrice','sellPrice')})
    return result


def validate_quote(provider, asset, q, now):
    spec = SPEC[asset]
    value = number(q['price'])
    if q.get('unit') != 'USD/troy_ounce' or q.get('source_url') != URLS[provider]:
        raise GoldError('Global metal source/unit changed.')
    if not Decimal(spec[6]) <= value <= Decimal(spec[7]):
        raise GoldError('Global metal price is outside its reviewed USD bounds.')
    fresh(stamp(q['updated_at']), now)
    if not re.fullmatch('[a-f0-9]{64}', q.get('page_hash', '')):
        raise GoldError('Global metal source evidence is missing.')
    if provider == 'alanchand':
        if q.get('basis') != 'published_spot' or value != number(q['visible_usd']) or value != number(q['structured_usd']):
            raise GoldError('Alanchand global evidence changed.')
        if not 0 <= (stamp(q['expiry'])-stamp(q['updated_at'])).total_seconds() <= 7200:
            raise GoldError('Alanchand global expiry is not its source date.')
    else:
        bid, ask = number(q['bid']), number(q['ask'])
        if q.get('basis') != 'midpoint' or bid > ask or (bid+ask)/2 != value or (ask-bid)/value > Decimal('.005'):
            raise GoldError('Global metal sides/midpoint/spread are invalid.')
        if provider == 'dolarchand' and number(q['usd_field']) != value:
            raise GoldError('DolarChand USD evidence changed.')
        if provider == 'servix':
            meta, current = q['catalog_record'], q['current_record']
            # Recheck catalog/value/observation evidence at final publication.
            if (meta['code'] != spec[1] or current['code'] != spec[1] or meta['qualityStatus'] != 'ACCEPTED' or
                    meta['quoteUnit'] != 'USD' or current['quoteUnit'] != 'USD' or
                    meta['labelEn'] != spec[5] or current['labelEn'] != spec[5] or
                    meta['providers'] != ['SERVIX'] or meta['providerSupported'] is not True or
                    meta['latestValueAvailable'] is not True or meta['stale'] is not False or
                    meta['availabilityStatus'] not in {'FRESH', 'AVAILABLE'} or meta['qualityMessage'] not in (None, '') or
                    stamp(meta['businessTime']) != stamp(q['updated_at']) or
                    stamp(current['businessTime']) != stamp(q['updated_at']) or
                    number(meta['latestValue']) != value or number(current['value']) != value or
                    number(current['midPrice']) != value or number(current['buyPrice']) != bid or number(current['sellPrice']) != ask or
                    not re.fullmatch('[a-f0-9]{64}', q.get('catalog_hash', ''))):
                raise GoldError('Servix global source evidence changed.')
    return value


def assess(providers, now):
    if not isinstance(providers, dict) or set(providers)-set(URLS):
        raise GoldError('Unreviewed global-metals provider.')
    rows = []
    for asset, spec in SPEC.items():
        eligible, rejected = {}, {}
        for provider, board in providers.items():
            try:
                eligible[provider] = validate_quote(provider, asset, board[asset], now)
            except (GoldError, KeyError, TypeError, ValueError) as exc:
                rejected[provider] = str(exc) if isinstance(exc, GoldError) else 'Incomplete exact instrument.'
        groups = []
        for size in range(2, len(eligible)+1):
            for ids in combinations(sorted(eligible), size):
                prices = [eligible[p] for p in ids]
                clocks = [stamp(providers[p][asset]['updated_at']) for p in ids]
                gap = (max(prices)-min(prices))/((max(prices)+min(prices))/2)*100
                # Published board times cannot prove an instrument's business
                # time. Require the authenticated per-instrument observation as
                # the freshness anchor, even when both public boards agree.
                if 'servix' in ids and gap <= LIMIT and (max(clocks)-min(clocks)).total_seconds() <= MAX_SKEW:
                    groups.append((ids, gap))
        if not groups:
            raise GoldError('No fresh Servix observation and synchronized agreeing publisher for global ' + asset + '.')
        size = max(len(g[0]) for g in groups)
        winners = [g for g in groups if len(g[0]) == size]
        if len(winners) != 1:
            raise GoldError('Global ' + asset + ' has ambiguous agreeing clusters.')
        ids, gap = winners[0]
        middle = sorted(eligible[p] for p in ids)
        median = (middle[len(middle)//2]+middle[(len(middle)-1)//2])/2
        selected = min(ids, key=lambda p: (abs(eligible[p]-median), p=='servix', p))
        for p in set(eligible)-set(ids):
            rejected[p] = 'Outside the unique synchronized agreeing cluster.'
        rows.append(dict(id=asset, name=spec[0], price=str(eligible[selected]), sources=list(ids), selected_source=selected,
            agreement_pct=str(gap.quantize(Decimal('.0001'))), rejected_sources=rejected, day=None, week=None))
    clocks = [stamp(providers[p][r['id']]['updated_at']) for r in rows for p in r['sources']]
    if (max(clocks)-min(clocks)).total_seconds() > MAX_SKEW:
        raise GoldError('Gold and silver observations are not synchronized for a ratio.')
    return rows


def validate(snapshot, now=None):
    now = now or datetime.now(UTC)
    if snapshot.get('layout_sample') or snapshot.get('status') != 'verified' or snapshot.get('schema_version') != 1:
        raise GoldError('Only a verified live global-metals snapshot can be published.')
    if not -5 <= (now-stamp(snapshot['generated_at'])).total_seconds() <= 180:
        raise GoldError('Global-metals collection expired.')
    expected = assess(snapshot['providers'], now)
    fields = ('id', 'name', 'price', 'sources', 'selected_source', 'agreement_pct')
    if len(snapshot['rows']) != 2 or any(a[k] != b[k] for a,b in zip(expected, snapshot['rows']) for k in fields):
        raise GoldError('Displayed global-metals rows differ from verified source values.')
    if snapshot.get('ratio') != str(number(expected[0]['price'])/number(expected[1]['price'])):
        raise GoldError('Gold-to-silver ratio differs from verified prices.')


def collect():
    def one(provider):
        if provider == 'servix':
            key = load_key()
            raw, chash = fetch(CATALOG, key)
            current, digest = fetch(URLS[provider], key)
            board = parse_servix(json_data(raw), json_data(current), datetime.now(UTC))
            for q in board.values():
                q['catalog_hash'] = chash
        else:
            raw, digest = fetch(URLS[provider])
            board = (parse_alan if provider=='alanchand' else parse_dolar_global)(raw, datetime.now(UTC))
        for q in board.values():
            q['page_hash'] = digest
        return board
    providers, health = {}, {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(one,p): p for p in URLS}
        for future in as_completed(tasks):
            p = tasks[future]
            try:
                providers[p] = future.result(); health[p] = {'status':'ok'}
            except Exception as exc:
                providers[p] = {}; health[p] = dict(status='excluded', detail=str(exc) if isinstance(exc,GoldError) else type(exc).__name__)
    snapshot = dict(schema_version=1, generated_at=datetime.now(UTC).isoformat(), providers=providers, health=health, rows=[])
    try:
        snapshot['rows'] = assess(providers, datetime.now(UTC))
        snapshot.update(status='verified', ratio=str(number(snapshot['rows'][0]['price'])/number(snapshot['rows'][1]['price'])))
        validate(snapshot)
    except GoldError as exc:
        snapshot.update(status='blocked', reason=str(exc))
    return snapshot
