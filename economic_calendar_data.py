"""Official, dated economic announcements; no forecasts or model-generated times."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo('Asia/Tehran')
MONTHS = 'January February March April May June July August September October November December'.split()
BLS = 'https://www.bls.gov/schedule/news_release/bls.ics'
BEA = 'https://www.bea.gov/news/schedule'
ECB = 'https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html'
ECB_TIME = 'https://www.ecb.europa.eu/press/govcdec/mopo/html/index.en.html'
BOE = 'https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates'
BOE_TIME = 'https://www.bankofengland.co.uk/monetary-policy'
HOSTS = {'www.bls.gov', 'www.bea.gov', 'www.ecb.europa.eu',
         'www.bankofengland.co.uk', 'www.federalreserve.gov'}
RULES = {
    'fed': ('تصمیم نرخ بهره آمریکا', 'فدرال رزرو | FOMC', 'دلار، طلا و بیت‌کوین', 'US', 100),
    'ecb': ('تصمیم نرخ بهره منطقه یورو', 'بانک مرکزی اروپا | ECB', 'یورو و دلار', 'EU', 95),
    'boe': ('تصمیم نرخ بهره بریتانیا', 'بانک انگلستان | BoE', 'پوند و دلار', 'GB', 90),
    'cpi': ('تورم مصرف‌کننده آمریکا', 'شاخص قیمت مصرف‌کننده | CPI', 'دلار، طلا و کریپتو', 'US', 100),
    'ppi': ('تورم تولیدکننده آمریکا', 'شاخص قیمت تولیدکننده | PPI', 'دلار و طلا', 'US', 75),
    'jobs': ('گزارش اشتغال آمریکا', 'اشتغال و نرخ بیکاری | NFP', 'دلار، طلا و کریپتو', 'US', 85),
    'eci': ('هزینه اشتغال آمریکا', 'شاخص هزینه اشتغال | ECI', 'دلار و انتظارات تورمی', 'US', 65),
    'jolts': ('فرصت‌های شغلی آمریکا', 'گزارش فرصت‌های شغلی | JOLTS', 'دلار و بازار کار', 'US', 60),
    'pce': ('تورم مخارج مصرفی آمریکا', 'درآمد و مخارج شخصی | PCE', 'دلار، طلا و کریپتو', 'US', 90),
    'gdp': ('رشد اقتصادی آمریکا', 'تولید ناخالص داخلی | GDP', 'دلار و چشم‌انداز رشد', 'US', 70),
}


class CalendarError(RuntimeError):
    pass


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise CalendarError('Calendar URL is outside the reviewed official sources.')


def fetch(url):
    validate_url(url)
    req = Request(url, headers={'User-Agent': 'KianiExchange-EconomicCalendar/1.0',
                                'Accept': 'text/html,text/calendar;q=0.9'})
    with build_opener(OfficialRedirect()).open(req, timeout=20) as response:
        validate_url(response.url)
        data = response.read(2_000_001)
        charset = response.headers.get_content_charset() or 'utf-8'
    if not data or len(data) > 2_000_000:
        raise CalendarError('Empty or oversized official calendar.')
    return data.decode(charset, errors='replace')


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(' '.join(x.text() if isinstance(x, Node) else x
                                for x in self.children).split())

    def nodes(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.nodes(tag)

    def has(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'br', 'hr', 'img', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(n.tag in {'script', 'style'} for n in self.stack):
            self.stack[-1].children.append(data)


def stamp(day, clock, zone):
    """Interpret the publisher's wall clock using IANA rules on the event date."""
    return datetime.combine(day, time.fromisoformat(clock), ZoneInfo(zone))


def event(kind, moment, source, evidence, time_source=None):
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise CalendarError('An event has no source timezone.')
    validate_url(source)
    title, label, watch, flag, priority = RULES[kind]
    return dict(id=kind + '-' + moment.date().isoformat(), kind=kind,
                source_url=source, time_source_url=time_source or source,
                evidence=evidence[:700], title_fa=title, label_fa=label,
                watch_fa=watch, flag=flag, priority=priority,
                source_local=moment.isoformat(), source_timezone=moment.tzinfo.key,
                utc=moment.astimezone(timezone.utc).isoformat(),
                tehran=moment.astimezone(TEHRAN).isoformat())


def classify(title, agency):
    if agency == 'BLS':
        for phrase, kind in (('Consumer Price Index', 'cpi'), ('Producer Price Index', 'ppi'),
                             ('Employment Situation', 'jobs'), ('Employment Cost Index', 'eci'),
                             ('Job Openings and Labor Turnover', 'jolts')):
            if title.startswith(phrase):
                return kind
    if agency == 'BEA':
        if title.startswith('Personal Income and Outlays'):
            return 'pce'
        if title.startswith(('GDP (', 'Gross Domestic Product (')):
            return 'gdp'
    return None


def parse_ics(text, source, agency):
    if 'BEGIN:VCALENDAR' not in text or 'END:VCALENDAR' not in text:
        raise CalendarError('Not a complete official iCalendar.')
    text = re.sub(r'\r?\n[ \t]', '', text)
    result, known = [], {}
    for block in re.findall(r'BEGIN:VEVENT\s*(.*?)END:VEVENT', text, re.S):
        props = {}
        for line in block.splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                name, *parameters = key.split(';')
                props[name.upper()] = (value.strip(), dict(x.split('=', 1) for x in parameters if '=' in x))
        title = props.get('SUMMARY', ('', {}))[0]
        kind = classify(title, agency)
        if not kind:
            continue
        uid = props.get('UID', ('', {}))[0]
        if not uid:
            raise CalendarError('A selected iCalendar event has no UID.')
        sequence = int(props.get('SEQUENCE', ('0', {}))[0])
        revision = (sequence, props.get('LAST-MODIFIED', props.get('DTSTAMP', ('', {})))[0])
        if uid in known and known[uid][0] >= revision:
            continue
        known[uid] = (revision, kind, props, title)
    for _, kind, props, title in known.values():
        if props.get('STATUS', ('', {}))[0].upper() == 'CANCELLED':
            continue
        if 'RRULE' in props:
            raise CalendarError('Recurring calendar entries require a reviewed expansion rule.')
        value, params = props.get('DTSTART', ('', {}))
        if params.get('VALUE') == 'DATE' or len(value) == 8:
            raise CalendarError('A selected release has only a date, not a release time.')
        fmt = '%Y%m%dT%H%M%S' if len(value.rstrip('Z')) == 15 else '%Y%m%dT%H%M'
        if value.endswith('Z'):
            moment = datetime.strptime(value[:-1], fmt).replace(tzinfo=ZoneInfo('UTC'))
        else:
            zone = params.get('TZID', '').strip('"')
            zone = {'US-Eastern': 'America/New_York', 'Eastern Standard Time': 'America/New_York'}.get(zone, zone)
            if not zone:
                raise CalendarError('A selected iCalendar release has a floating time.')
            moment = datetime.strptime(value, fmt).replace(tzinfo=ZoneInfo(zone))
        result.append(event(kind, moment, source, f'{title}; DTSTART {value}; {params}'))
    if not known:
        raise CalendarError('No reviewed event types found in the official calendar.')
    return result


def months_between(start, end):
    cursor = start.replace(day=1)
    while cursor < end:
        yield cursor.year, cursor.month
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def collect_bls(start, end):
    try:
        rows = parse_ics(fetch(BLS), BLS, 'BLS')
        if max(datetime.fromisoformat(row['utc']) for row in rows) < end:
            raise CalendarError('BLS iCalendar does not cover the upcoming window; checking monthly pages.')
        return rows
    except Exception:
        # An official HTML format is an alternative source, never a stale cache.
        result = []
        for year, month in months_between(start.date(), end.date()):
            url = f'https://www.bls.gov/schedule/{year}/{month:02}_sched_list.htm'
            doc = Document(fetch(url)).root
            if 'All times on calendar are Eastern Time' not in doc.text():
                raise CalendarError('BLS timezone notice is missing.')
            recognized = 0
            for row in doc.nodes('tr'):
                cells = [n.text() for n in row.nodes('td')]
                if len(cells) != 3:
                    continue
                kind = classify(cells[2], 'BLS')
                if kind:
                    day = datetime.strptime(cells[0], '%A, %B %d, %Y').date()
                    if (day.year, day.month) != (year, month):
                        raise CalendarError('BLS month/date mismatch.')
                    clock = datetime.strptime(cells[1], '%I:%M %p').strftime('%H:%M')
                    result.append(event(kind, stamp(day, clock, 'America/New_York'), url, ' | '.join(cells)))
                    recognized += 1
            if recognized == 0:
                raise CalendarError('BLS release rows were not recognized.')
        return result


def collect_bea(start, end):
    doc = Document(fetch(BEA)).root
    result = []
    for table in doc.nodes('table'):
        years = re.findall(r'\bYear (20\d{2})\b', table.text())
        if len(set(years)) != 1:
            continue
        year = int(years[0])
        for row in table.nodes('tr'):
            cells = list(row.nodes('td'))
            if not cells:
                continue
            titles = [c.text() for c in cells if c.has('release-title')]
            if len(titles) != 1:
                continue
            kind = classify(titles[0], 'BEA')
            if not kind:
                continue
            dates = [c for c in cells if c.has('scheduled-date')]
            if len(dates) != 1:
                raise CalendarError('BEA date cell is missing.')
            content = dates[0].text()
            if 'To Be Announced' in content:
                continue
            match = re.fullmatch(r'([A-Za-z]+ \d{1,2}) (\d{1,2}:\d{2} [AP]M)', content)
            if not match:
                raise CalendarError('BEA date/time format changed.')
            moment = datetime.strptime(f'{year} {match[1]} {match[2]}', '%Y %B %d %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York'))
            result.append(event(kind, moment, BEA, content + ' | ' + titles[0]))
    if not result:
        raise CalendarError('BEA release table was not recognized.')
    return result


def collect_fed(start, end):
    result = []
    for year, month in months_between(start.date(), end.date()):
        url = f'https://www.federalreserve.gov/newsevents/{year}-{MONTHS[month - 1].lower()}.htm'
        doc = Document(fetch(url)).root
        if f'{MONTHS[month - 1]} {year}' not in doc.text() or 'FOMC Meetings' not in doc.text():
            raise CalendarError('Fed calendar month/section is missing.')
        for panel in doc.nodes('div'):
            if not panel.has('panel-unstyled'):
                continue
            parts = {key: [n.text() for n in panel.nodes('div') if n.has(key)]
                     for key in ('col-xs-2', 'col-xs-7', 'col-xs-3')}
            titles = parts['col-xs-7']
            if len(titles) != 1 or not titles[0].startswith('FOMC Meeting'):
                continue
            if any(len(parts[k]) != 1 for k in parts):
                raise CalendarError('Fed announcement fields changed.')
            clock = parts['col-xs-2'][0].replace('p.m.', 'PM').replace('a.m.', 'AM')
            clock = datetime.strptime(clock, '%I:%M %p').strftime('%H:%M')
            day = date(year, month, int(parts['col-xs-3'][0]))
            result.append(event('fed', stamp(day, clock, 'America/New_York'), url, panel.text()))
    return result


def collect_ecb(start, end):
    schedule = Document(fetch(ECB)).root.text()
    notice = Document(fetch(ECB_TIME)).root.text()
    if '14:15 CET' not in notice:
        raise CalendarError('ECB official release-time notice changed.')
    pattern = r'(\d{2}/\d{2}/20\d{2})\s+(Governing Council of the ECB:\s*monetary policy meeting[^\d]*?\(Day 2\))'
    rows = re.findall(pattern, schedule)
    if not rows:
        raise CalendarError('ECB monetary-policy decision dates were not recognized.')
    return [event('ecb', stamp(datetime.strptime(day, '%d/%m/%Y').date(), '14:15', 'Europe/Berlin'),
                  ECB, day + ' ' + description, ECB_TIME) for day, description in rows]


def collect_boe(start, end):
    doc = Document(fetch(BOE)).root
    if '12 noon' not in Document(fetch(BOE_TIME)).root.text():
        raise CalendarError('BoE official release-time notice changed.')
    year, result = None, []
    for n in doc.nodes():
        if n.tag == 'h2':
            m = re.fullmatch(r'(20\d{2}) confirmed dates', n.text())
            year = int(m[1]) if m else None
        if n.tag == 'tr' and year:
            cells = list(n.nodes('td'))
            if len(cells) == 2 and 'MPC Summary and minutes' in cells[1].text():
                day = datetime.strptime(f'{cells[0].text()} {year}', '%A %d %B %Y').date()
                result.append(event('boe', stamp(day, '12:00', 'Europe/London'), BOE, n.text(), BOE_TIME))
    if not result:
        raise CalendarError('BoE confirmed announcement dates were not recognized.')
    return result


COLLECTORS = {'BLS': collect_bls, 'BEA': collect_bea, 'Fed': collect_fed,
              'ECB': collect_ecb, 'BoE': collect_boe}


def window(now, next_week=False):
    local = now.astimezone(TEHRAN)
    day = local.date() + timedelta(days=(5 - local.weekday()) % 7)
    if next_week and day == local.date():
        day += timedelta(days=7)
    start = stamp(day, '10:00', 'Asia/Tehran')
    return start, start + timedelta(days=7)


def collect(start, end):
    def one(item):
        name, collector = item
        try:
            rows = collector(start, end)
            return name, rows, dict(status='ok', event_count=len(rows))
        except Exception as exc:
            return name, [], dict(status='failed', error_type=type(exc).__name__,
                                  http_status=exc.code if isinstance(exc, HTTPError) else None,
                                  detail=str(exc) if isinstance(exc, CalendarError) else None)
    all_rows, health = [], {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for name, rows, state in pool.map(one, COLLECTORS.items()):
            all_rows.extend(rows)
            health[name] = state
    # Failing closed avoids presenting a falsely complete week with a major
    # central-bank decision or inflation report silently missing.
    if any(s['status'] != 'ok' for s in health.values()):
        exc = CalendarError('Official source verification incomplete; no post created.')
        exc.health = health
        raise exc
    unique = {}
    for row in all_rows:
        t = datetime.fromisoformat(row['tehran'])
        if not start <= t < end:
            continue
        old = unique.get(row['id'])
        if old and old['utc'] != row['utc']:
            raise CalendarError('Conflicting official release times; review required.')
        unique[row['id']] = row
    ranked = sorted(unique.values(), key=lambda x: (-x['priority'], x['utc'], x['id']))
    selected = sorted(ranked[:6], key=lambda x: (x['utc'], -x['priority'], x['id']))
    if not selected:
        raise CalendarError('No reviewed upcoming releases in this seven-day window; no post created.')
    return dict(generated_at=datetime.now(timezone.utc).isoformat(), timezone='Asia/Tehran',
                window_start=start.isoformat(), window_end=end.isoformat(),
                sources=health, events=selected, omitted_ids=[x['id'] for x in ranked[6:]])


def validate(snapshot, *, publishing=False):
    start = datetime.fromisoformat(snapshot['window_start'])
    end = datetime.fromisoformat(snapshot['window_end'])
    generated = datetime.fromisoformat(snapshot['generated_at'])
    if snapshot['timezone'] != 'Asia/Tehran' or start.tzinfo is None or end - start != timedelta(days=7):
        raise CalendarError('Invalid seven-day Tehran calendar.')
    if set(snapshot['sources']) != set(COLLECTORS) or any(x['status'] != 'ok' for x in snapshot['sources'].values()):
        raise CalendarError('Every reviewed calendar must be verified before publication.')
    if not 1 <= len(snapshot['events']) <= 6:
        raise CalendarError('Calendar requires one to six verified events.')
    seen = set()
    for row in snapshot['events']:
        moment = datetime.fromisoformat(row['source_local'])
        if row['id'] in seen or row['kind'] not in RULES:
            raise CalendarError('Invalid or duplicate calendar event.')
        seen.add(row['id'])
        source_zone = ZoneInfo(row['source_timezone'])
        source_wall = moment.replace(tzinfo=None).replace(tzinfo=source_zone)
        if (source_wall.utcoffset() != moment.utcoffset()
            or moment.astimezone(timezone.utc).isoformat() != row['utc']
            or moment.astimezone(TEHRAN).isoformat() != row['tehran'] or not start <= moment < end):
            raise CalendarError('Event timezone/window mismatch.')
        for field in ('source_url', 'time_source_url'):
            validate_url(row[field])
        if publishing and moment <= datetime.now(timezone.utc) + timedelta(minutes=5):
            raise CalendarError('An event is no longer sufficiently in the future; recollect the calendar.')
    if publishing:
        now = datetime.now(timezone.utc)
        if not timedelta(0) <= now - generated <= timedelta(minutes=20):
            raise CalendarError('Calendar source verification expired; recollect before posting.')
        if not start <= now.astimezone(TEHRAN) < start + timedelta(hours=2):
            raise CalendarError('Outside the approved Saturday 10:00 Tehran publication window.')
