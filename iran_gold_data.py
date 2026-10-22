"""Dated Iran gold quotes and shared guards; unknown data never becomes a post."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import time as runtime_time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from economic_calendar_data import Document, TEHRAN

UTC = timezone.utc
MAX_QUOTE_AGE = 30 * 60
MAX_COLLECTION_AGE = 180
DOLAR = 'https://dolarchand.com/en/gold-silver'
ASSETS = (
    ('emami', 'سکه امامی', 'sekee', 'Emami', 'COIN_EMAMI', 80_000_000, 600_000_000),
    ('bahar', 'سکه بهار آزادی', 'sekeb', 'Azadi', 'COIN_BAHAR', 80_000_000, 600_000_000),
    ('half', 'نیم سکه', 'nim', '½ Azadi', 'COIN_HALF', 40_000_000, 320_000_000),
    ('quarter', 'ربع سکه', 'rob', '¼ Azadi', 'COIN_QUARTER', 20_000_000, 160_000_000),
    ('gram_coin', 'سکه گرمی', 'gerami', 'Gerami', 'COIN_GERAMI', 10_000_000, 80_000_000),
    ('gold18', 'طلای ۱۸ عیار', 'geram18', 'Gold 18K', 'GOLD_18K', 8_000_000, 60_000_000),
    ('mesghal', 'مثقال طلا', 'mesghal', 'Gold Mesghal (Bazaar)', 'GOLD_MESGHAL', 35_000_000, 260_000_000),
)
SPEC = {row[0]: row for row in ASSETS}
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


class GoldError(RuntimeError):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


def number(raw):
    if isinstance(raw, bool):
        raise GoldError('Boolean is not a price.')
    text = str(raw).translate(DIGITS).strip().replace('٬', ',')
    if not re.fullmatch(r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?', text):
        raise GoldError('Invalid price representation.')
    try:
        value = Decimal(text.replace(',', ''))
    except InvalidOperation:
        raise GoldError('Invalid numeric quote.') from None
    if not value.is_finite() or value <= 0:
        raise GoldError('Non-positive or non-finite price.')
    return value


def validate_url(url):
    p = urlsplit(url)
    slugs = {x[2] for x in ASSETS}
    valid = (p.hostname == 'www.tgju.org' and p.path in {'/profile/' + x for x in slugs} or
             p.hostname == 'api.tgju.org' and p.path in {'/v1/market/indicator/summary-table-data/' + x for x in slugs} or
             p.hostname == 'dolarchand.com' and p.path == '/en/gold-silver' or
             p.hostname == 'alanchand.com' and p.path == '/gold-price')
    if p.scheme != 'https' or not valid or p.username or p.password or p.port not in (None, 443):
        raise GoldError('Unreviewed gold source URL.')


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    validate_url(url)
    request = Request(url, headers={'User-Agent': 'KianiExchange-GoldVerifier/1.0',
                                  'Accept': 'text/html,application/json',
                                  'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'})
    deadline = runtime_time.monotonic() + 35
    with build_opener(Redirect()).open(request, timeout=15) as response:
        validate_url(response.url)
        if urlsplit(response.url).path != urlsplit(url).path:
            raise GoldError('Source redirected to a different instrument.')
        chunks, size = [], 0
        # read1 performs at most one underlying read. A single large read can
        # otherwise keep resetting the socket timeout on a drip-fed response.
        while size <= 2_000_000:
            if runtime_time.monotonic() >= deadline:
                raise GoldError('Gold source response exceeded its time budget.', 'source_timeout')
            chunk = response.read1(min(64 * 1024, 2_000_001 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        body = b''.join(chunks)
    if not body or len(body) > 2_000_000:
        raise GoldError('Empty or oversized gold source.')
    return body.decode('utf-8'), hashlib.sha256(body).hexdigest()


def stamp(value):
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        raise GoldError('Invalid source timestamp.') from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise GoldError('Source timestamp has no timezone.')
    return moment.astimezone(UTC)


def fresh(moment, now):
    age = (now.astimezone(UTC) - moment.astimezone(UTC)).total_seconds()
    if not -60 <= age <= MAX_QUOTE_AGE:
        raise GoldError(f'Source quote is stale or future-dated (age {int(age)}s).', 'stale')
    if moment.astimezone(TEHRAN).date() != now.astimezone(TEHRAN).date():
        raise GoldError('Source quote belongs to a previous Tehran day.', 'stale')


def parse_tgju(html, history, asset, now):
    doc = Document(html).root
    text = doc.text()
    if not re.search(r'واحد پولی\s*:?\s*ریال', text):
        raise GoldError('TGJU quote does not declare its rial unit.')
    unit = 'گرم' if asset == 'gold18' else 'مثقال' if asset == 'mesghal' else 'عدد'
    if not re.search(r'واحد حجمی\s*:?\s*' + unit, text):
        raise GoldError('TGJU instrument volume unit changed.')
    wanted = {'نرخ فعلی', 'زمان ثبت آخرین نرخ', 'بالاترین قیمت روز', 'پایین ترین قیمت روز'}
    fields = {}
    for table in doc.nodes('table'):
        found = {}
        for row in table.nodes('tr'):
            cells = [x.text() for x in row.children if getattr(x, 'tag', '') == 'td']
            if len(cells) == 2 and cells[0] in wanted:
                if cells[0] in found:
                    raise GoldError('Duplicate TGJU current-quote field.')
                found[cells[0]] = cells[1]
        if wanted <= set(found):
            if fields:
                raise GoldError('Ambiguous TGJU quote table.')
            fields = found
    if not wanted <= set(fields):
        raise GoldError('TGJU current quote table is incomplete.')
    rial = number(fields['نرخ فعلی'])
    if not number(fields['پایین ترین قیمت روز']) <= rial <= number(fields['بالاترین قیمت روز']):
        raise GoldError('TGJU price is outside its published daily range.')
    rows = history.get('data') if isinstance(history, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or len(rows[0]) != 8:
        raise GoldError('TGJU dated daily record is missing or changed shape.')
    row = rows[0]
    try:
        day = datetime.strptime(row[6].translate(DIGITS), '%Y/%m/%d').date()
        import jdatetime
        jalali = jdatetime.date.fromgregorian(date=day)
        if row[7].translate(DIGITS) != f'{jalali.year:04}/{jalali.month:02}/{jalali.day:02}':
            raise GoldError('TGJU Gregorian and Persian source dates disagree.')
    except (TypeError, ValueError, AttributeError):
        raise GoldError('TGJU dated daily record has an invalid date.') from None
    if number(row[3]) != rial:
        raise GoldError('TGJU profile price disagrees with its dated daily record.')
    raw_time = fields['زمان ثبت آخرین نرخ'].translate(DIGITS)
    clock = re.fullmatch(r'(\d{1,2}:\d{2}(?::\d{2})?)', raw_time)
    if day != now.astimezone(TEHRAN).date():
        raise GoldError('TGJU quote is from ' + day.isoformat() + ', not today.', 'stale')
    if not clock:
        # A date-only old quote must not become fresh just because its page was fetched.
        if re.fullmatch(r'\d{1,2}\s+[آ-ی]+', raw_time):
            raise GoldError('TGJU exposes a date-only quote without a current clock.', 'stale')
        raise GoldError('TGJU source quote has no recognized clock.')
    try:
        updated = datetime.combine(day, time.fromisoformat(clock[1].zfill(8) if len(clock[1]) > 5 else clock[1].zfill(5)), TEHRAN)
    except ValueError:
        raise GoldError('TGJU quote clock is invalid.') from None
    fresh(updated, now)
    toman = rial / Decimal(10)
    if toman != toman.to_integral_value():
        raise GoldError('TGJU rial value cannot convert to an integral toman price.')
    return dict(price=str(toman), updated_at=updated.astimezone(UTC).isoformat(),
                original_rial=str(rial), unit='rial', date_evidence=[row[6], row[7]],
                clock_evidence=raw_time)


def tgju_one(asset, now):
    slug = SPEC[asset][2]
    url = 'https://www.tgju.org/profile/' + slug
    history_url = 'https://api.tgju.org/v1/market/indicator/summary-table-data/' + slug + '?lang=fa&order_dir=desc&order_col=timestamp&length=2&start=0'
    html, page_hash = fetch(url)
    raw_history, history_hash = fetch(history_url)
    quote = parse_tgju(html, json.loads(raw_history), asset, now)
    quote.update(source_url=url, history_url=history_url, page_hash=page_hash, history_hash=history_hash)
    return quote


def parse_dolar(html, now):
    doc = Document(html).root
    text = doc.text()
    if 'prices in Toman' not in text:
        raise GoldError('DolarChand page no longer declares prices in toman.')
    decoder, chunks = json.JSONDecoder(), []
    for match in re.finditer(r'self\.__next_f\.push\(', html):
        try:
            value, _ = decoder.raw_decode(html[match.end():].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
            chunks.append(value[1])
    stream = ''.join(chunks)
    times = set(re.findall(r'"initialIso"\s*:\s*"([^"\n]+)"', stream))
    if len(times) != 1:
        raise GoldError('DolarChand has no unambiguous source snapshot timestamp.')
    iso = next(iter(times))
    updated = stamp(iso)
    visible = re.search(r'Last updated ([A-Za-z]{3} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M)', text)
    if not visible or datetime.strptime(visible[1], '%b %d, %Y, %I:%M %p') != updated.replace(tzinfo=None, second=0, microsecond=0):
        raise GoldError('DolarChand visible timestamp disagrees with its ISO snapshot timestamp.')
    rate_maps = []
    for match in re.finditer(r'"rates"\s*:', stream):
        try:
            value, _ = decoder.raw_decode(stream[match.end():].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {x[4] for x in ASSETS} <= set(value):
            rate_maps.append(value)
    if len(rate_maps) != 1:
        raise GoldError('DolarChand source quote map is missing or ambiguous.')
    rates = rate_maps[0]
    visible_rows = {}
    names = {x[3]: x[0] for x in ASSETS}
    for row in doc.nodes('tr'):
        cells = [x.text() for x in row.children if getattr(x, 'tag', '') == 'td']
        if cells and cells[0] in names:
            key = names[cells[0]]
            if key in visible_rows or len(cells) < 3:
                raise GoldError('DolarChand quote rows are ambiguous.')
            visible_rows[key] = cells
    quotes = {}
    for asset, spec in SPEC.items():
        value = rates[spec[4]]
        bid, ask = number(value['buy']), number(value['sell'])
        if asset not in visible_rows or number(visible_rows[asset][1]) != bid or number(visible_rows[asset][2]) != ask:
            raise GoldError('DolarChand visible and structured quotes disagree for ' + asset)
        if bid > ask or (ask - bid) / ((ask + bid) / 2) > Decimal('0.01'):
            raise GoldError('DolarChand buy/sell pair is crossed or too wide.')
        quotes[asset] = dict(bid=str(bid), ask=str(ask), price=str((bid + ask) / 2),
                             updated_at=updated.isoformat(), source_url=DOLAR, unit='toman')
    fresh(updated, now)
    return quotes


def dolar(now):
    html, digest = fetch(DOLAR)
    quotes = parse_dolar(html, now)
    for row in quotes.values():
        row['page_hash'] = digest
    return quotes


def coherent(values):
    for asset, spec in SPEC.items():
        value = number(values[asset])
        if not Decimal(spec[5]) <= value <= Decimal(spec[6]):
            raise GoldError('Price outside conservative toman range: ' + asset)
    p = {key: number(value) for key, value in values.items()}
    if not min(p['emami'], p['bahar']) > p['half'] > p['quarter'] > p['gram_coin']:
        raise GoldError('Coin denominations have an inconsistent price ordering.')
    # Iranian bazaar mesghal is quoted at fineness705; 18K gram at750.
    if not Decimal('4.28') <= p['mesghal'] / p['gold18'] <= Decimal('4.38'):
        raise GoldError('18K gram and bazaar mesghal prices have inconsistent units/ratio.')


def assess(primary, secondary, now, baseline=None):
    if set(primary) != set(SPEC) or set(secondary) != set(SPEC):
        raise GoldError('Both feeds must contain all seven exact instruments.')
    for rows in (primary, secondary):
        coherent({key: quote['price'] for key, quote in rows.items()})
    result = []
    for asset, spec in SPEC.items():
        a, b = primary[asset], secondary[asset]
        fresh(stamp(a['updated_at']), now)
        fresh(stamp(b['updated_at']), now)
        pa, pb = number(a['price']), number(b['price'])
        if (pa != pa.to_integral_value() or a['unit'] != 'rial' or number(a['original_rial']) / 10 != pa or b['unit'] != 'toman' or
                number(b['bid']) > number(b['ask']) or (number(b['bid']) + number(b['ask'])) / 2 != pb or
                (number(b['ask']) - number(b['bid'])) / pb > Decimal('0.01')):
            raise GoldError('Rial/toman normalization or bid/ask validation failed: ' + asset)
        spread = abs(pa - pb) / ((pa + pb) / 2) * 100
        limit = Decimal('0.50') if asset in {'gold18', 'mesghal'} else Decimal('1.00')
        if spread > limit:
            raise GoldError(f'Feeds disagree for {asset}: {spread:.2f}% exceeds {limit}%.')
        if baseline and asset in baseline:
            move = abs(pa / number(baseline[asset]) - 1) * 100
            if move > 7:
                raise GoldError(f'{asset} moved {move:.2f}% from the last published price; manual review needed.', 'jump')
        result.append(dict(id=asset, name=spec[1], price=str(pa), day=None, month=None,
                           agreement_pct=str(spread.quantize(Decimal('0.0001')))))
    return result


def collect(baseline=None):
    from iran_gold_quorum import collect as collect_quorum
    return collect_quorum(baseline)


def validate(snapshot, *, publishing=False, now=None, baseline=None):
    now = now or datetime.now(UTC)
    if snapshot.get('layout_sample') or snapshot.get('status') != 'verified' or snapshot.get('timezone') != 'Asia/Tehran':
        raise GoldError('Only a verified gold snapshot may be rendered/published.')
    generated = stamp(snapshot['generated_at'])
    if not -5 <= (now - generated).total_seconds() <= MAX_COLLECTION_AGE:
        raise GoldError('Gold collection expired; fetch again.', 'stale')
    keys = ('id', 'name', 'price', 'agreement_pct')
    if snapshot.get('schema_version') == 2:
        from iran_gold_quorum import assess as assess_quorum
        expected = assess_quorum(snapshot['providers'], now, baseline)
        keys += ('sources', 'selected_source')
    else:
        # Legacy private snapshots remain readable, with the original two-feed
        # checks. New collections always use version 2 and provider consensus.
        expected = assess(snapshot['primary'], snapshot['secondary'], now, baseline)
    if len(snapshot['rows']) != 7 or any(any(a[k] != b[k] for k in keys)
                                        for a, b in zip(expected, snapshot['rows'])):
        raise GoldError('Displayed gold board differs from its verified source values.')
    if publishing:
        local = now.astimezone(TEHRAN)
        if not time(10) <= local.time() < time(10, 15):
            raise GoldError('Gold posting is allowed only 10:00–10:15 Tehran.')


def percent(current, previous):
    if previous is None:
        return None
    value = (number(current) / number(previous) - 1) * 100
    if abs(value) > 100:
        return None  # Do not display a suspect historical comparison.
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
