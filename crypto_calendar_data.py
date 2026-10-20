"""Fresh official crypto schedules; explicit clocks, separate date-only estimates.

No language model invents, translates or predicts an activation time. Source
adapters deliberately reject formats they do not understand. This is a selected
calendar, not a complete registry of every chain or token.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from economic_calendar_data import CalendarError, Document, TEHRAN

UTC = timezone.utc
ETH_FEED = 'https://blog.ethereum.org/en/feed.xml'
PLASMA = 'https://www.plasma.org/docs/get-started/xpl/tokenomics'
DERIBIT = 'https://www.deribit.com/api/v2/public/get_instruments'
RELEASES = {'BNB': 'bnb-chain/bsc', 'TRON': 'tronprotocol/java-tron'}
POLICY = 'https://support.deribit.com/hc/en-us/articles/25944688876957-Contract-Introduction-Policy'
STATUS_FA = {'official': 'زمان‌بندی رسمی', 'estimated': 'تخمینی؛ برآورد از برنامه واگذاری'}


def validate_url(url):
    p = urlsplit(url)
    safe = (p.hostname == 'blog.ethereum.org' and p.path.startswith('/en/') or
            p.hostname == 'www.plasma.org' and p.path == '/docs/get-started/xpl/tokenomics' or
            p.hostname == 'www.deribit.com' and p.path == '/api/v2/public/get_instruments' or
            p.hostname == 'support.deribit.com' and p.path.startswith('/hc/en-us/articles/25944688876957') or
            p.hostname == 'api.github.com' and any(p.path == '/repos/' + repo + '/releases' for repo in RELEASES.values()) or
            p.hostname == 'github.com' and any(p.path.startswith('/' + repo + '/releases/') for repo in RELEASES.values()))
    if p.scheme != 'https' or not safe or p.username or p.password or p.port not in (None, 443):
        raise CalendarError('Crypto calendar URL is outside the reviewed official sources.')


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    validate_url(url)
    request = Request(url, headers={'User-Agent': 'KianiExchange-CryptoCalendar/1.0',
                                  'Accept': 'application/json,application/xml,text/html;q=0.9'})
    with build_opener(Redirect()).open(request, timeout=25) as response:
        validate_url(response.url)
        body = response.read(3_000_001)
    if not body or len(body) > 3_000_000:
        raise CalendarError('Empty or oversized crypto schedule source.')
    return body.decode('utf-8')


def exact_event(key, moment, *, family, title, label, watch, source, evidence, network=None, priority=70):
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise CalendarError('An official clock must have an explicit source timezone.')
    moment = moment.astimezone(UTC)
    return dict(id=key, family=family, precision='second', status='official',
                title_fa=title, label_fa=label, watch_fa=watch, network=network,
                priority=priority, source_url=source, evidence=evidence[:1600],
                utc=moment.isoformat(), tehran=moment.astimezone(TEHRAN).isoformat(),
                tehran_date=moment.astimezone(TEHRAN).date().isoformat(),
                status_fa=STATUS_FA['official'])


def ethereum(start, end):
    feed = ET.fromstring(fetch(ETH_FEED))
    items = feed.findall('./channel/item')
    if not items:
        raise CalendarError('Ethereum official feed has no recognizable items.')
    candidates = []
    for item in items[:60]:
        title, link = item.findtext('title', ''), item.findtext('link', '')
        published = parsedate_to_datetime(item.findtext('pubDate', ''))
        if not published or published.tzinfo is None:
            raise CalendarError('Ethereum feed item has no explicit publication timezone.')
        if (published >= start - timedelta(days=120) and
                re.search(r'\b(?:testnet|mainnet|upgrade)\b.*\bannouncement\b', title, re.I)):
            candidates.append((published, title, link))
    if len(candidates) > 8:
        raise CalendarError('Ethereum announcement discovery exceeded its reviewed bound.')
    result, seen = [], set()
    for _, title, link in sorted(candidates, reverse=True):
        doc = Document(fetch(link)).root
        fork = title.split()[0]
        if not re.fullmatch('[A-Za-z0-9-]{2,30}', fork):
            raise CalendarError('Ethereum upgrade name requires review.')
        found = False
        for table in doc.nodes('table'):
            rows = list(table.nodes('tr'))
            if not rows:
                continue
            cells = lambda row: [x.text() for x in row.children if getattr(x, 'tag', '') in {'th', 'td'}]
            headers = cells(rows[0])
            if 'Network' not in headers or 'UTC Time' not in headers or 'UNIX Timestamp' not in headers:
                continue
            found = True
            for row in rows[1:]:
                values = cells(row)
                if len(values) != len(headers):
                    raise CalendarError('Ethereum deployment table changed shape.')
                data = dict(zip(headers, values))
                network = data['Network']
                if network.lower() not in {'mainnet', 'sepolia', 'hoodi', 'holesky'}:
                    raise CalendarError('Ethereum deployment table contains an unreviewed network.')
                key = fork.lower(), network.lower()
                if key in seen:
                    continue
                seen.add(key)  # A newer TBD or cancellation supersedes an older date.
                if data['UTC Time'].upper() in {'TBD', 'TBA', 'N/A', '-', 'CANCELLED', 'CANCELED'}:
                    continue
                moment = datetime.strptime(data['UTC Time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
                if int(data['UNIX Timestamp'].replace(',', '')) != int(moment.timestamp()):
                    raise CalendarError('Ethereum UTC clock disagrees with its published Unix timestamp.')
                mainnet = network.lower() == 'mainnet'
                result.append(exact_event('eth-' + '-'.join(key), moment, family='Ethereum',
                    title='ارتقای ' + fork + ' اتریوم',
                    label='شبکه اصلی اتریوم' if mainnet else 'شبکه آزمایشی ' + network,
                    watch='تغییرات شبکه اصلی' if mainnet else 'آزمایش ارتقا؛ تاریخ مین‌نت مستقل است',
                    source=link, evidence=table.text(), network='mainnet' if mainnet else 'testnet',
                    priority=100 if mainnet else 65))
        if not found:
            raise CalendarError('Ethereum announcement has no reviewed UTC deployment table: ' + link)
    return result


CLOCK = re.compile(r'(20\d{2}-\d{2}-\d{2})[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\s*(?:UTC|Z|\+00:00)\b', re.I)
NETWORK = re.compile(r'\b(?:chapel(?:\s+testnet)?|nile(?:\s+testnet)?|shasta(?:\s+testnet)?|mainnet|testnet)\b', re.I)


def releases(family, start, end):
    repo = RELEASES[family]
    rows = json.loads(fetch('https://api.github.com/repos/' + repo + '/releases?per_page=10'))
    if not isinstance(rows, list) or not rows:
        raise CalendarError(f'{family} release API has no recognizable releases.')
    result, seen = [], set()
    for item in rows:  # GitHub returns newest first. Never use release publication time as activation.
        if item.get('draft'):
            continue
        body = item.get('body') or ''
        for raw_line in body.replace('\r', '').splitlines():
            line = re.sub(r'[*`]', '', raw_line).strip()
            if not re.search(r'schedul|activat|hard\s*fork', line, re.I):
                continue
            for clock in CLOCK.finditer(line):
                preceding = line[:clock.start()]
                networks = list(NETWORK.finditer(preceding))
                if not networks or re.search(r'cancel|postpon|not scheduled|TBD|TBA|estimated|approximately', line, re.I):
                    continue
                network = networks[-1].group().lower()
                network_key = 'mainnet' if network == 'mainnet' else network.split()[0]
                if network_key in seen:
                    continue
                seen.add(network_key)
                day, hour, minute, second, ampm = clock.groups()
                hour = int(hour)
                if ampm:
                    if not 1 <= hour <= 12:
                        raise CalendarError('Invalid 12-hour source clock.')
                    hour = hour % 12 + (12 if ampm.upper() == 'PM' else 0)
                moment = datetime.combine(date.fromisoformat(day), time(hour, int(minute), int(second or 0)), UTC)
                stamps = re.findall(r'\b(1\d{9})\b', line)
                if stamps and any(int(x) != int(moment.timestamp()) for x in stamps):
                    raise CalendarError(f'{family} UTC clock disagrees with its Unix timestamp.')
                mainnet = network_key == 'mainnet'
                version = item.get('tag_name', '')
                if not re.fullmatch('[A-Za-z0-9.()_-]{1,55}', version):
                    raise CalendarError(f'{family} release version needs review.')
                result.append(exact_event(f'{family.lower()}-{network_key}', moment, family=family,
                    title='ارتقای ' + ('BNB Chain' if family == 'BNB' else 'TRON'),
                    label=('شبکه اصلی' if mainnet else 'شبکه آزمایشی ' + network_key.title()) + ' · ' + version,
                    watch='تغییرات شبکه اصلی' if mainnet else 'آزمایش ارتقا؛ تاریخ مین‌نت مستقل است',
                    source=item['html_url'], evidence=line, network='mainnet' if mainnet else 'testnet',
                    priority=95 if mainnet else 60))
    return result


def plasma(start, end):
    text = Document(fetch(PLASMA)).root.text()
    proofs = (
        'mainnet beta launch (September 25, 2025)',
        'The remaining 32% (3,200,000,000 XPL) unlocks monthly on a pro-rata basis over the following three-year period',
        'One-third of the XPL team tokens are subject to a one-year cliff',
        'September 25, 2026',
        'The remaining two-thirds are unlocked monthly on a pro-rata basis over the following two-year period',
        'XPL sold to investors are unlocked on the same schedule as the team allocation',
        'September 25, 2028',
    )
    if not all(x in text for x in proofs):
        raise CalendarError('Plasma vesting terms changed; the date-only estimate requires review.')
    result = []
    for year, month in {(start.year, start.month), (end.year, end.month)}:
        day = date(year, month, 25)
        # The public document defines monthly vesting, not an exact release clock.
        # Individual vesting start dates may differ; do not publish an amount.
        if not date(2025, 10, 25) <= day <= date(2028, 9, 25):
            continue
        result.append(dict(id='xpl-monthly-' + day.isoformat(), family='Plasma', precision='date',
            status='estimated', status_fa=STATUS_FA['estimated'], title_fa='آزادسازی ماهانه XPL',
            label_fa='Plasma · ساعت اعلام نشده', watch_fa='برنامه عرضه توکن؛ مقدار قطعی اعلام نشده',
            source_url=PLASMA, evidence=' | '.join(proofs), priority=80,
            tehran_date=day.isoformat(), utc=None, tehran=None, network=None,
            inference='Date estimated from the monthly launch-anniversary vesting schedule. No exact time or quantity claimed.'))
    return result


def deribit(start, end):
    dates = {}
    for currency in ('BTC', 'ETH'):
        url = DERIBIT + '?currency=' + currency + '&kind=option&expired=false'
        body = json.loads(fetch(url))
        instruments = body.get('result')
        if body.get('error') or not isinstance(instruments, list) or not instruments:
            raise CalendarError('Deribit returned no verifiable option instruments.')
        dates[currency] = {}
        for item in instruments:
            if item.get('kind') != 'option' or item.get('is_active') is not True:
                continue
            moment = datetime.fromtimestamp(int(item['expiration_timestamp']) / 1000, UTC)
            # Select the actual listed end-of-month expiry, not every daily Friday expiry.
            if moment.weekday() != 4 or (moment + timedelta(days=7)).month == moment.month:
                continue
            if moment.time() != time(8):
                raise CalendarError('Deribit monthly expiry clock changed; review required.')
            name = item.get('instrument_name', '')
            expected = currency + '-' + str(moment.day) + moment.strftime('%b%y').upper() + '-'
            if not name.startswith(expected):
                raise CalendarError('Deribit instrument name and expiration timestamp disagree.')
            dates[currency].setdefault(moment, name)
    result = []
    for moment in sorted(set(dates['BTC']) & set(dates['ETH'])):
        row = exact_event('deribit-monthly-' + moment.date().isoformat(), moment, family='Deribit',
            title='سررسید پایان ماه آپشن‌های', label='بیت‌کوین و اتریوم در دریبیت',
            watch='تسویه قراردادها و پوشش ریسک', source=POLICY,
            evidence=json.dumps({c: dict(instrument=dates[c][moment], expiration_timestamp=int(moment.timestamp() * 1000))
                                 for c in ('BTC', 'ETH')}, sort_keys=True), priority=90)
        row['verification_urls'] = [DERIBIT + '?currency=' + c + '&kind=option&expired=false' for c in ('BTC', 'ETH')]
        result.append(row)
    return result


COLLECTORS = {'Ethereum': ethereum, 'BNB': lambda s, e: releases('BNB', s, e),
              'TRON': lambda s, e: releases('TRON', s, e), 'Plasma': plasma, 'Deribit': deribit}


def window(now):
    local = now.astimezone(TEHRAN)
    day = local.date() + timedelta(days=(4 - local.weekday()) % 7)
    start = datetime.combine(day, time(18), TEHRAN)
    return start, start + timedelta(days=7)


def in_window(row, start, end):
    if row['precision'] == 'date':
        # Include only whole Tehran civil dates within the window. No midnight is
        # represented as an event clock. Exclude uncertain boundary-day events.
        return start.date() < date.fromisoformat(row['tehran_date']) < end.date()
    return start <= datetime.fromisoformat(row['utc']) < end


def collect(start, end):
    def one(item):
        name, collector = item
        try:
            rows = collector(start, end)
            return name, rows, dict(status='ok', parsed_events=len(rows), eligible_events=sum(in_window(r, start, end) for r in rows))
        except Exception as exc:
            return name, [], dict(status='failed', error_type=type(exc).__name__,
                                  http_status=exc.code if isinstance(exc, HTTPError) else None,
                                  detail=str(exc) if isinstance(exc, CalendarError) else None)
    all_rows, health = [], {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for name, rows, state in pool.map(one, COLLECTORS.items()):
            all_rows.extend(rows)
            health[name] = state
    if any(x['status'] != 'ok' for x in health.values()):
        exc = CalendarError('Official crypto source verification incomplete; no post created.')
        exc.health = health
        raise exc
    eligible = {row['id']: row for row in all_rows if in_window(row, start, end)}
    ranked = sorted(eligible.values(), key=lambda x: (-x['priority'], x['tehran_date'], x['id']))
    selected = sorted(ranked[:6], key=lambda x: (x['tehran_date'], x['utc'] or '', x['id']))
    if not selected:
        raise CalendarError('No qualifying crypto events in this seven-day window; no post created.')
    return dict(generated_at=datetime.now(UTC).isoformat(), timezone='Asia/Tehran',
                window_start=start.isoformat(), window_end=end.isoformat(), sources=health,
                events=selected, omitted_ids=[x['id'] for x in ranked[6:]])


def validate(snapshot, *, publishing=False):
    start, end, generated = (datetime.fromisoformat(snapshot[x]) for x in ('window_start', 'window_end', 'generated_at'))
    if (snapshot['timezone'] != 'Asia/Tehran' or start.tzinfo is None or generated.tzinfo is None or
            start.astimezone(TEHRAN) != start or start.utcoffset() != timedelta(hours=3, minutes=30) or
            start.weekday() != 4 or start.time() != time(18) or end - start != timedelta(days=7)):
        raise CalendarError('Invalid Friday 18:00 Tehran crypto calendar window.')
    if set(snapshot['sources']) != set(COLLECTORS) or any(x['status'] != 'ok' for x in snapshot['sources'].values()):
        raise CalendarError('Every reviewed crypto source must verify before publication.')
    if not 1 <= len(snapshot['events']) <= 6:
        raise CalendarError('Crypto calendar requires one to six sourced events.')
    seen = set()
    now = datetime.now(UTC)
    for row in snapshot['events']:
        validate_url(row['source_url'])
        for url in row.get('verification_urls', []):
            validate_url(url)
        if (row['id'] in seen or row['family'] not in COLLECTORS or not row.get('evidence') or
                row['status_fa'] != STATUS_FA.get(row['status']) or not in_window(row, start, end)):
            raise CalendarError('Invalid, duplicate or unsourced crypto event.')
        seen.add(row['id'])
        if row['precision'] == 'date':
            if row['status'] != 'estimated' or row['family'] != 'Plasma' or row['utc'] is not None or row['tehran'] is not None:
                raise CalendarError('A date-only estimate must not contain an invented clock.')
        elif row['precision'] == 'second':
            moment = datetime.fromisoformat(row['utc'])
            if (row['status'] != 'official' or moment.tzinfo is None or moment.utcoffset() != timedelta(0) or
                    moment.astimezone(TEHRAN).isoformat() != row['tehran'] or
                    moment.astimezone(TEHRAN).date().isoformat() != row['tehran_date']):
                raise CalendarError('Crypto event clock/timezone mismatch.')
            if row['family'] in {'Ethereum', 'BNB', 'TRON'}:
                if row['network'] not in {'mainnet', 'testnet'} or ('آزمایشی' in row['label_fa']) != (row['network'] == 'testnet'):
                    raise CalendarError('Testnet/mainnet label mismatch.')
            if publishing and moment <= now + timedelta(minutes=5):
                raise CalendarError('A crypto event is no longer sufficiently in the future.')
        else:
            raise CalendarError('Unknown crypto event time precision.')
    if publishing and (not timedelta(0) <= now - generated <= timedelta(minutes=20) or
                       not start <= now.astimezone(TEHRAN) < start + timedelta(hours=2)):
        raise CalendarError('Outside Friday 18:00–20:00 Tehran or source verification expired.')
