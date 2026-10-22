"""Two-provider consensus per instrument; failed providers cannot veto valid peers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import json
import re
from urllib.error import HTTPError

from iran_gold_data import (ASSETS, DIGITS, SPEC, TEHRAN, UTC, Document, GoldError,
                           coherent, dolar, fetch, fresh, number, stamp, tgju_one)

ALAN = 'https://alanchand.com/gold-price'
PROVIDERS = {
    'tgju': ('TGJU', 'https://www.tgju.org/gold-chart'),
    'dolarchand': ('DolarChand', 'https://dolarchand.com/en/gold-silver'),
    'alanchand': ('Alanchand', ALAN),
}
ALAN_NAMES = {
    'emami': 'سکه امامی (طرح جدید)', 'bahar': 'سکه بهار آزادی',
    'half': 'نیم سکه', 'quarter': 'ربع سکه', 'gram_coin': 'سکه گرمی',
    'gold18': 'گرم طلای 18 عیار', 'mesghal': 'آبشده(مثقال طلا)',
}
MONTHS = 'فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند'.split()
WEEKDAYS = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')


def parse_alanchand(html, now):
    doc = Document(html).root
    text = doc.text().translate(DIGITS)
    # This is the provider's displayed board update time, never retrieval time
    # or the Offer expiry. Expiry is used only to verify the timezone/date.
    dates = re.findall(r'آخرین بروز رسانی\s*:\s*(\d{2}:\d{2})\s+(\S+)\s+(\d{1,2})\s+(\S+)\s+(\d{4})', text)
    if len(dates) != 1:
        raise GoldError('Alanchand has no unambiguous dated board update clock.')
    clock, weekday, day, month, year = dates[0]
    try:
        import jdatetime
        calendar_day = jdatetime.date(int(year), MONTHS.index(month) + 1, int(day)).togregorian()
        updated = datetime.combine(calendar_day, time.fromisoformat(clock), TEHRAN)
    except (ValueError, TypeError):
        raise GoldError('Alanchand board date/clock is invalid.') from None
    if weekday.replace('\u200c', '') != WEEKDAYS[calendar_day.weekday()].replace('\u200c', ''):
        raise GoldError('Alanchand weekday disagrees with its Persian date.')
    fresh(updated, now)
    lists = []
    for script in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.S):
        try:
            value = json.loads(script)
        except json.JSONDecodeError:
            raise GoldError('Alanchand structured price data is invalid JSON.') from None
        if isinstance(value, dict) and value.get('@type') == 'ItemList':
            lists.append(value)
    if len(lists) != 1:
        raise GoldError('Alanchand structured price list is missing or ambiguous.')
    products = {}
    for entry in lists[0].get('itemListElement', []):
        product = entry.get('item', {})
        name = product.get('name')
        if name in ALAN_NAMES.values():
            if name in products:
                raise GoldError('Duplicate Alanchand product.')
            products[name] = product.get('offers', {})
    visible = {}
    for table in doc.nodes('table'):
        if not table.has('goldTbl'):
            continue
        headers = [x.text() for x in table.nodes('th')]
        if headers[:3] != ['', 'قیمت (تومان) + تغییرات', 'قیمت واقعی']:
            raise GoldError('Alanchand market/intrinsic price columns changed.')
        for row in table.nodes('tr'):
            cells = [x for x in row.children if getattr(x, 'tag', '') == 'td']
            if cells and cells[0].text() in ALAN_NAMES.values():
                name = cells[0].text()
                if name in visible or len(cells) != 4:
                    raise GoldError('Alanchand instrument row is ambiguous.')
                if cells[1].attrs.get('data-label') != 'قیمت (تومان) + تغییرات':
                    raise GoldError('Alanchand market-price unit/column changed.')
                # The first column is the market price. Intrinsic value and
                # bubble columns must never be used as independent quotes.
                match = re.fullmatch(r'([0-9,]+) تومان\s*[+-]?[0-9.]+%', cells[1].text().translate(DIGITS))
                if not match:
                    raise GoldError('Alanchand visible market price changed shape.')
                visible[name] = number(match[1])
    quotes = {}
    for asset, name in ALAN_NAMES.items():
        offer = products.get(name, {})
        if offer.get('priceCurrency') != 'IRR' or name not in visible:
            raise GoldError('Alanchand exact instrument or currency is missing: ' + asset)
        rial, toman = number(offer.get('price')), visible[name]
        if rial / 10 != toman or toman != toman.to_integral_value():
            raise GoldError('Alanchand visible toman and structured rial prices disagree: ' + asset)
        expiry = stamp(offer.get('priceValidUntil'))
        raw_expiry = datetime.fromisoformat(offer['priceValidUntil'])
        if (raw_expiry.utcoffset() != updated.utcoffset() or
                expiry.astimezone(TEHRAN).date() != calendar_day or
                not 0 <= (expiry - updated).total_seconds() <= 2 * 3600):
            raise GoldError('Alanchand board clock and structured timezone/date disagree.')
        quotes[asset] = dict(price=str(toman), original_rial=str(rial), unit='toman',
            updated_at=updated.astimezone(UTC).isoformat(), source_url=ALAN,
            date_evidence=f'{year}/{MONTHS.index(month)+1:02}/{int(day):02}', clock_evidence=clock)
    return quotes


def alanchand(now):
    html, digest = fetch(ALAN)
    quotes = parse_alanchand(html, now)
    for row in quotes.values():
        row['page_hash'] = digest
    return quotes


def quote_price(provider, asset, quote, now):
    """Recheck original evidence at collection and immediately before publication."""
    fresh(stamp(quote['updated_at']), now)
    price = number(quote['price'])
    spec = SPEC[asset]
    if not Decimal(spec[5]) <= price <= Decimal(spec[6]):
        raise GoldError('Price outside conservative toman range: ' + asset)
    if provider == 'tgju':
        expected_url = 'https://www.tgju.org/profile/' + spec[2]
        if quote['unit'] != 'rial' or number(quote['original_rial']) / 10 != price or price != price.to_integral_value():
            raise GoldError('TGJU exact rial/toman conversion failed.')
    elif provider == 'dolarchand':
        expected_url = PROVIDERS[provider][1]
        bid, ask = number(quote['bid']), number(quote['ask'])
        if quote['unit'] != 'toman' or bid > ask or (bid + ask) / 2 != price or (ask - bid) / price > Decimal('0.01'):
            raise GoldError('DolarChand unit or bid/ask validation failed.')
    elif provider == 'alanchand':
        expected_url = ALAN
        if quote['unit'] != 'toman' or number(quote['original_rial']) / 10 != price or price != price.to_integral_value():
            raise GoldError('Alanchand exact rial/toman conversion failed.')
    else:
        raise GoldError('Unreviewed consensus provider.')
    if quote.get('source_url') != expected_url or not re.fullmatch('[0-9a-f]{64}', quote.get('page_hash', '')):
        raise GoldError('Quote source identity/content evidence changed.')
    return price


def assess(providers, now, baseline=None):
    if not isinstance(providers, dict) or set(providers) - set(PROVIDERS):
        raise GoldError('Unreviewed or malformed provider registry.')
    board_errors = {}
    for provider, board in providers.items():
        try:
            if not isinstance(board, dict) or set(board) - set(SPEC):
                raise GoldError('Provider returned a malformed instrument board.')
            prices = {key: number(quote['price']) for key, quote in board.items()}
            if set(prices) == set(SPEC):
                coherent(prices)
            else:
                # A failed TGJU instrument does not discard other valid TGJU
                # instruments, but observable cross-instrument errors still do.
                for high, low in [('emami', 'half'), ('bahar', 'half'),
                                  ('half', 'quarter'), ('quarter', 'gram_coin')]:
                    if high in prices and low in prices and prices[high] <= prices[low]:
                        raise GoldError('Provider coin denominations are inconsistent.')
                if 'mesghal' in prices and 'gold18' in prices and not Decimal('4.28') <= prices['mesghal'] / prices['gold18'] <= Decimal('4.38'):
                    raise GoldError('Provider gold fineness/volume ratio is inconsistent.')
        except (GoldError, KeyError, TypeError, ValueError) as exc:
            board_errors[provider] = str(exc) if isinstance(exc, GoldError) else 'Incomplete board evidence.'
    result = []
    for asset, spec in SPEC.items():
        eligible, rejected = {}, {}
        for provider, board in providers.items():
            try:
                if provider in board_errors:
                    raise GoldError(board_errors[provider])
                if not isinstance(board, dict) or asset not in board:
                    raise GoldError('Exact instrument unavailable.')
                eligible[provider] = quote_price(provider, asset, board[asset], now)
            except (GoldError, KeyError, TypeError, ValueError) as exc:
                rejected[provider] = str(exc) if isinstance(exc, GoldError) else 'Incomplete quote evidence.'
        limit = Decimal('0.50') if asset in {'gold18', 'mesghal'} else Decimal('1.00')
        def spread(ids):
            low, high = min(eligible[k] for k in ids), max(eligible[k] for k in ids)
            return (high - low) / ((high + low) / 2) * 100
        clusters = [ids for size in range(2, len(eligible) + 1)
                    for ids in combinations(sorted(eligible), size) if spread(ids) <= limit]
        if not clusters:
            raise GoldError(f'No two current providers agree for {asset}; eligible={sorted(eligible)}; rejected={rejected}.', 'quorum')
        largest = max(map(len, clusters))
        winners = [ids for ids in clusters if len(ids) == largest]
        if len(winners) != 1:
            raise GoldError('Ambiguous equal-size price clusters for ' + asset + '; no price selected.', 'disagreement')
        accepted = winners[0]
        # Choose an actual quote nearest the consensus median, rather than
        # manufacturing an average market quote. Provider name breaks exact ties.
        prices = sorted(eligible[k] for k in accepted)
        median = (prices[(largest - 1) // 2] + prices[largest // 2]) / 2
        selected = min(accepted, key=lambda k: (abs(eligible[k] - median), k))
        price = eligible[selected].quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        if baseline and asset in baseline and abs(price / number(baseline[asset]) - 1) * 100 > 7:
            raise GoldError(asset + ' moved over 7% from the last successful board; manual review needed.', 'jump')
        for provider in set(eligible) - set(accepted):
            rejected[provider] = 'Outside the unique largest agreeing cluster.'
        result.append(dict(id=asset, name=spec[1], price=str(price), day=None, month=None,
            agreement_pct=str(spread(accepted).quantize(Decimal('0.0001'))),
            sources=list(accepted), selected_source=selected, rejected_sources=rejected))
    coherent({row['id']: row['price'] for row in result})
    return result


def collect(baseline=None):
    providers = {name: {} for name in PROVIDERS}
    health = {name: {'status': 'blocked', 'instruments': {}} for name in PROVIDERS}
    def one(key):
        provider, asset = key
        try:
            now = datetime.now(UTC)
            value = tgju_one(asset, now) if asset else (dolar(now) if provider == 'dolarchand' else alanchand(now))
            return key, value, None
        except Exception as exc:
            return key, None, dict(code=exc.code if isinstance(exc, GoldError) else 'source',
                error_type=type(exc).__name__, http_status=exc.code if isinstance(exc, HTTPError) else None,
                detail=str(exc) if isinstance(exc, GoldError) else 'Provider request/parsing failed.')
    jobs = [('dolarchand', None), ('alanchand', None), *[('tgju', asset) for asset in SPEC]]
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks = [pool.submit(one, job) for job in jobs]
        for completed in as_completed(tasks):
            (provider, asset), value, error = completed.result()
            print('Gold provider:', provider + ('/' + asset if asset else ''),
                  'blocked (' + str(error['code']) + ')' if error else 'parsed', flush=True)
            if asset:
                health[provider]['instruments'][asset] = dict(status='blocked' if error else 'ok', **(error or {}))
                if value:
                    providers[provider][asset] = value
            else:
                health[provider].update(status='blocked' if error else 'ok', **(error or {}))
                if value:
                    providers[provider] = value
    count = len(providers['tgju'])
    health['tgju']['status'] = 'ok' if count == len(SPEC) else 'partial' if count else 'blocked'
    snapshot = dict(schema_version=2, generated_at=datetime.now(UTC).isoformat(), timezone='Asia/Tehran',
                    health=health, providers=providers, rows=[])
    try:
        snapshot['rows'] = assess(providers, datetime.now(UTC), baseline)
        snapshot.update(status='verified', code='verified', reason='All seven prices have a unique consensus of at least two providers.')
    except GoldError as exc:
        snapshot.update(status='blocked', code=exc.code, reason=str(exc))
    return snapshot


def accepted_quotes(snapshot):
    return [snapshot['providers'][source][row['id']] for row in snapshot['rows'] for source in row['sources']]


def accepted_sources(snapshot):
    return sorted({source for row in snapshot['rows'] for source in row['sources']})
