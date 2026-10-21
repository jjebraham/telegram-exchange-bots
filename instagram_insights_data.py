"""Read-only Meta transport and publication discovery for post performance tracking.

This module has no publish, edit, archive or delete operation. Credentials stay
in the Authorization header and Graph error bodies are never logged or saved.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

UTC = timezone.utc
KINDS = ('rates', 'economy', 'crypto', 'top50', 'iran_gold', 'calendar', 'crypto_calendar')
METRICS = ('views', 'reach', 'likes', 'comments', 'saved', 'shares',
           'total_interactions', 'profile_visits', 'follows')
STATE = Path.home() / '.local/state/kiani-instagram-insights'
STORY_CONFIG = Path.home() / '.local/state/kiani-instagram-stories/config.json'
RUNTIME = ('instagram_insights_data.py', 'instagram_post_insights.py', 'instagram_news_retention.py')
NEWS_RUNTIME = ('instagram_ranked_news.py', 'crypto_news_trial.py', 'instagram_news_batch.py', 'instagram_insights_data.py',
    'selector_trial_runtime/economy_news_picker.py', 'selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py', 'selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md')
MAX_CALLS = 100


class InsightsError(RuntimeError):
    pass


class GraphError(InsightsError):
    def __init__(self, category, http_status=None, code=None, subcode=None):
        self.category, self.http_status = category, http_status
        self.code, self.subcode = code, subcode
        super().__init__('Meta read failed: ' + category)

    def safe(self):
        return dict(status=self.category, http_status=self.http_status,
                    code=self.code, subcode=self.subcode)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{5,32}', value):
        raise InsightsError('Expected a numeric Instagram account or media ID.')
    return value


def count(value):
    # A missing result must never be silently converted to a zero.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or int(value) != value:
        return None
    return int(value)


def moment(value):
    if not isinstance(value, str):
        raise InsightsError('Meta did not supply a publication timestamp.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise InsightsError('Publication timestamp is invalid.') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise InsightsError('Publication timestamp has no timezone.')
    return result.timestamp()


def fingerprint(root):
    return hashlib.sha256(b'\0'.join(name.encode() + b'\0' + (Path(root) / name).read_bytes()
                                   for name in RUNTIME)).hexdigest()


def private_file(path):
    if path.is_symlink() or not path.is_file():
        raise InsightsError('Required private configuration is missing or is a symlink.')
    if hasattr(os, 'getuid') and path.stat().st_uid != os.getuid():
        raise InsightsError('Private configuration has an unexpected owner.')
    return path


def story_config():
    data = json.loads(private_file(STORY_CONFIG).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('sources'), dict):
        raise InsightsError('The existing Story source configuration is invalid.')
    if not {'rates', 'economy', 'crypto', 'top50'} <= set(data['sources']):
        raise InsightsError('Expected existing publisher sources are missing.')
    return data


def read_db(path):
    """Do not create or modify an existing publisher database."""
    path = Path(path)
    if not path.is_file():
        raise InsightsError('Publication database is missing.')
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def inventory(config, cutoff):
    """Only track IDs recorded by our publishers/Story registry, not manual posts."""
    records, health = {}, {}

    def add(raw_id, kind):
        media_id = identifier(str(raw_id))
        if kind not in KINDS:
            raise InsightsError('Unknown publisher category.')
        if media_id in records and records[media_id] != kind:
            raise InsightsError('A media ID has conflicting publisher categories.')
        records[media_id] = kind

    try:
        con = read_db(config['db'])
        try:
            rows = con.execute('''SELECT feed_id,kind FROM stories
                WHERE discovered_at>=? OR published_at>=?
                ORDER BY discovered_at DESC LIMIT 2000''', (cutoff, cutoff)).fetchall()
            for row in rows:
                add(row['feed_id'], row['kind'])
        finally:
            con.close()
        health['story_registry'] = 'ok'
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, InsightsError) as exc:
        health['story_registry'] = type(exc).__name__
    for kind, raw_path in config['sources'].items():
        if kind not in KINDS:
            continue
        try:
            path = Path(raw_path)
            if kind == 'rates':
                data = json.loads(path.read_text(encoding='utf-8'))
                if data.get('mode') != 'feed':
                    raise InsightsError('Expected a published Feed state.')
                add(data.get('media_id'), kind)
            else:
                table = 'top50_publications' if kind == 'top50' else 'instagram_news_publications'
                con = read_db(path)
                try:
                    for row in con.execute(f'''SELECT media_id FROM {table}
                        WHERE status='published' AND finished_at>=?
                        ORDER BY finished_at DESC LIMIT 1000''', (cutoff,)):
                        add(row['media_id'], kind)
                finally:
                    con.close()
            health[kind] = 'ok'
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, InsightsError) as exc:
            health[kind] = type(exc).__name__
    return records, health


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GraphError('redirect_refused', code)


class Graph:
    """GET only, fixed host, bounded calls, sanitized errors, no URL credentials."""
    def __init__(self):
        self.account_id = identifier(os.getenv('INSTAGRAM_USER_ID', '').strip())
        self.token = os.getenv('INSTAGRAM_ACCESS_TOKEN', '').strip()
        self.version = os.getenv('INSTAGRAM_GRAPH_API_VERSION', '').strip().strip('/')
        base = os.getenv('INSTAGRAM_GRAPH_BASE_URL', 'https://graph.facebook.com').strip().rstrip('/')
        if base != 'https://graph.facebook.com' or not re.fullmatch(r'v[0-9]{1,2}\.0', self.version):
            raise InsightsError('Expected the configured Facebook Login Graph host/version.')
        if not self.token or any(x in self.token for x in '\r\n'):
            raise InsightsError('The existing private Instagram token is not loaded.')
        self.base, self.calls, self.pressure = base + '/' + self.version, 0, False
        self.calls_limit, self.deadline = MAX_CALLS, time.monotonic() + 540
        self.opener = build_opener(NoRedirect())

    def usage(self, headers):
        for name in ('X-App-Usage', 'X-Business-Use-Case-Usage'):
            try:
                data = json.loads(headers.get(name, '{}'))
                def walk(value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            if (key in {'call_count', 'total_cputime', 'total_time'} and
                                not isinstance(item, bool) and isinstance(item, (int, float)) and math.isfinite(item) and item >= 80):
                                self.pressure = True
                            walk(item)
                    elif isinstance(value, list):
                        for item in value:
                            walk(item)
                walk(data)
            except (ValueError, TypeError):
                pass

    def get(self, node, edge='', params=None):
        identifier(node)
        if edge not in {'', '/media', '/insights', '/content_publishing_limit'}:
            raise InsightsError('Unreviewed analytics API route.')
        if self.calls >= self.calls_limit or time.monotonic() >= self.deadline:
            raise GraphError('request_budget')
        if self.pressure:
            raise GraphError('usage_pressure')
        self.calls += 1
        url = self.base + '/' + node + edge + '?' + urlencode(params or {})
        request = Request(url, method='GET', headers={'Accept': 'application/json',
            'Authorization': 'Bearer ' + self.token, 'User-Agent': 'KianiExchange-Insights/1.0'})
        status, error = None, None
        try:
            with self.opener.open(request, timeout=25) as response:
                self.usage(response.headers)
                raw = response.read(2_000_001)
        except HTTPError as exc:
            status = exc.code
            self.usage(exc.headers)
            raw = exc.read(8192)
        except (URLError, TimeoutError, OSError):
            raise GraphError('network') from None
        if len(raw) > 2_000_000:
            raise GraphError('oversized_response')
        try:
            payload = json.loads(raw)
            error = payload.get('error') if isinstance(payload, dict) else None
        except (ValueError, UnicodeError):
            raise GraphError('invalid_response', status) from None
        if status or error:
            error = error if isinstance(error, dict) else {}
            code, sub = count(error.get('code')), count(error.get('error_subcode'))
            category = ('authentication' if code == 190 or status == 401 else
                        'permission' if code in {10, 200, 294} or status == 403 else
                        'rate_limit' if code in {4, 17, 32, 613} or code is not None and 80000 <= code < 90000 or status == 429 else
                        'transient' if status is not None and status >= 500 or error.get('is_transient') is True else
                        'unavailable' if code in {100, 803} or status == 404 else 'api_error')
            raise GraphError(category, status, code, sub)
        if not isinstance(payload, dict):
            raise GraphError('invalid_response')
        return payload

    def owned_media(self, cutoff):
        account = self.get(self.account_id, params={'fields': 'id,username'})
        if str(account.get('id')) != self.account_id:
            raise InsightsError('Meta account does not match the configured publisher account.')
        after, seen, result = None, set(), {}
        for _ in range(5):
            params = {'fields': 'id,timestamp,media_type,media_product_type,caption,permalink', 'limit': '100'}
            if after:
                params['after'] = after
            payload = self.get(self.account_id, '/media', params)
            rows = payload.get('data')
            if not isinstance(rows, list):
                raise InsightsError('Meta media listing has no data array.')
            old = False
            for row in rows:
                if not isinstance(row, dict):
                    raise InsightsError('Meta media listing contains an invalid item.')
                media_id, when = identifier(str(row.get('id'))), moment(row.get('timestamp'))
                if when > time.time() + 60:
                    raise InsightsError('Meta publication timestamp is in the future.')
                if when < cutoff:
                    old = True
                    continue
                if media_id in result:
                    raise InsightsError('Meta returned a repeated media ID.')
                result[media_id] = row
            paging = payload.get('paging', {})
            if old or not rows or not isinstance(paging, dict) or not paging.get('next'):
                break
            # Never follow Graph's full next URL: it may contain credentials.
            cursor = paging.get('cursors', {}).get('after')
            if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in seen:
                raise InsightsError('Meta pagination cursor is invalid.')
            seen.add(cursor)
            after = cursor
        return account, result

    def publishing_quota(self):
        response = self.get(self.account_id, '/content_publishing_limit', {'fields': 'quota_usage,config'})
        rows = response.get('data')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise InsightsError('Publishing quota data is unavailable.')
        used, config = count(rows[0].get('quota_usage')), rows[0].get('config')
        if not isinstance(config, dict):
            raise InsightsError('Publishing quota configuration is unavailable.')
        total, duration = count(config.get('quota_total')), count(config.get('quota_duration'))
        if used is None or not total or duration != 86400:
            raise InsightsError('Expected an explicit rolling 24-hour publishing quota.')
        return dict(used=used, total=total, duration=duration, remaining=max(0, total - used))

    def metrics(self, media_id, names=METRICS):
        if not names or any(name not in METRICS for name in names):
            raise InsightsError('Unreviewed insights metric.')
        result = {}
        started = time.time()
        for metric in names:
            try:
                payload = self.get(media_id, '/insights', {'metric': metric})
                entries = payload.get('data')
                value = None
                if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict) and entries[0].get('name') == metric:
                    record = entries[0]
                    # Insights are cumulative lifetime observations, not daily sums.
                    if record.get('period') in {None, 'lifetime', 'total_over_range'}:
                        values, total = record.get('values'), record.get('total_value')
                        if isinstance(values, list) and len(values) == 1 and isinstance(values[0], dict):
                            value = count(values[0].get('value'))
                        elif isinstance(total, dict):
                            value = count(total.get('value'))
                result[metric] = dict(status='ok' if value is not None else 'missing', value=value)
            except GraphError as exc:
                if exc.category != 'unavailable':
                    raise
                result[metric] = dict(exc.safe(), value=None)
        return dict(started_at=started, observed_at=time.time(), metrics=result,
                    complete=all(result.get(name, {}).get('status') == 'ok' for name in METRICS))


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise InsightsError('Refusing an analytics database symlink.')
    con = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    con.row_factory = sqlite3.Row
    con.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posts(
            media_id TEXT PRIMARY KEY, kind TEXT NOT NULL, media_type TEXT NOT NULL,
            published_at REAL NOT NULL, title TEXT NOT NULL, permalink TEXT,
            first_seen_at REAL NOT NULL, metadata_at REAL NOT NULL,
            exposure TEXT NOT NULL DEFAULT 'unknown', manual_keep INTEGER NOT NULL DEFAULT 0,
            baseline_next REAL NOT NULL DEFAULT 0, baseline_attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS samples(
            id INTEGER PRIMARY KEY, media_id TEXT NOT NULL, started_at REAL NOT NULL,
            observed_at REAL NOT NULL, api_version TEXT NOT NULL,
            metrics_json TEXT NOT NULL, complete INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS checkpoints(
            media_id TEXT NOT NULL, hours INTEGER NOT NULL, status TEXT NOT NULL,
            sample_id INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, error_type TEXT,
            PRIMARY KEY(media_id,hours));
        CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL,
            status TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
            health_json TEXT NOT NULL DEFAULT '{}', error_json TEXT);
        CREATE TABLE IF NOT EXISTS decisions(
            media_id TEXT PRIMARY KEY, assessed_at REAL NOT NULL,
            status TEXT NOT NULL, details_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retention_jobs(
            media_id TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at REAL NOT NULL,
            views INTEGER, sample_id INTEGER, finished_at REAL, error_type TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}');
    ''')
    return con


def setting(con, key, default=None):
    row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(con, key, value):
    with con:
        con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))


def bind_account(con, account_id):
    saved = setting(con, 'account_id')
    if saved and saved != account_id:
        raise InsightsError('This analytics database belongs to another Instagram account.')
    set_setting(con, 'account_id', account_id)


def safe_link(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme == 'https' and parsed.netloc in {'www.instagram.com', 'instagram.com'} and re.fullmatch(r'/(?:p|reel)/[A-Za-z0-9_-]+/', parsed.path) and not parsed.query and not parsed.fragment:
        return value
    return None


def register(con, registry, owned, exposure='unknown'):
    now, matched = time.time(), 0
    for media_id, kind in registry.items():
        row = owned.get(media_id)
        if not row or row.get('media_type') not in {'IMAGE', 'CAROUSEL_ALBUM'} or row.get('media_product_type', 'FEED') != 'FEED':
            continue
        when = moment(row['timestamp'])
        lines = [line.strip() for line in str(row.get('caption') or '').splitlines() if line.strip()]
        title = next((line for line in lines if not line.startswith(('صرافی کیانی', 'kiani.exchange'))), '')[:240]
        existing = con.execute('SELECT kind,published_at FROM posts WHERE media_id=?', (media_id,)).fetchone()
        if existing and (existing['kind'] != kind or abs(existing['published_at'] - when) > 1):
            raise InsightsError('Stored publication metadata changed unexpectedly.')
        with con:
            con.execute('''INSERT INTO posts(media_id,kind,media_type,published_at,title,permalink,first_seen_at,metadata_at,exposure)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET
                title=excluded.title,permalink=excluded.permalink,metadata_at=excluded.metadata_at''',
                (media_id, kind, row['media_type'], when, title, safe_link(row.get('permalink')), now, now, exposure))
        matched += 1
    return matched
