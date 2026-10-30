"""Fail-closed two-hour retention for newly published direct Reels only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from instagram_insights_data import Graph, GraphError, InsightsError, count, identifier, moment, read_db
from instagram_news_retention import permission_proof

TRIAL_DB = Path.home() / '.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
INSIGHTS_DB = Path.home() / '.local/state/kiani-instagram-insights/insights.sqlite3'
AGE = 2 * 3600
GRACE = 30 * 60
GAP = 10 * 60
MINIMUM = 200
DIRECT_ORIGINS = {'admin_direct', 'daily_direct'}
def _table(con):
    con.execute('''CREATE TABLE IF NOT EXISTS direct_reel_retention(
        media_id TEXT PRIMARY KEY, reel_id TEXT NOT NULL, published_at REAL NOT NULL,
        status TEXT NOT NULL, first_views INTEGER, first_observed REAL,
        checked_at REAL NOT NULL, error_type TEXT, evidence_json TEXT NOT NULL DEFAULT '{}')''')
    con.execute('''CREATE TABLE IF NOT EXISTS direct_reel_retention_meta(
        key TEXT PRIMARY KEY, value TEXT NOT NULL)''')


def _meta(con, key, default=None):
    row = con.execute('SELECT value FROM direct_reel_retention_meta WHERE key=?', (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row['value'])
    except (ValueError, TypeError):
        return default


def _set_meta(con, key, value):
    con.execute('INSERT OR REPLACE INTO direct_reel_retention_meta(key,value) VALUES (?,?)',
                (key, json.dumps(value, ensure_ascii=False)))


def enable():
    """Set a one-time enrollment cutoff; repeated installs never widen it backward."""
    from instagram_trial_reels import _connect
    with _connect() as con:
        _table(con)
        if _meta(con, 'policy_version') not in (None, 1):
            raise InsightsError('A different direct Reel retention policy is already installed.')
        enabled_after = _meta(con, 'enabled_after')
        if enabled_after is None:
            _set_meta(con, 'enabled_after', time.time())
        elif (isinstance(enabled_after, bool) or
              not isinstance(enabled_after, (int, float)) or enabled_after <= 0):
            raise InsightsError('The direct Reel retention cutoff is invalid; deletion remains disabled.')
        if _meta(con, 'paused'):
            raise InsightsError('Direct Reel deletion is paused for manual review.')
        _set_meta(con, 'policy_version', 1)
        _set_meta(con, 'policy', dict(version=1, assessment_hours=2,
            keep_at_or_above_views=MINIMUM, grace_minutes=30, low_readings=2,
            minimum_gap_minutes=10))
        if _meta(con, 'paused') is None:
            _set_meta(con, 'paused', False)
        con.commit()
        return _meta(con, 'enabled_after')


def _note(con, media_id, status, *, views=None, observed=None, error=None, evidence=None):
    with con:
        con.execute('''UPDATE direct_reel_retention SET status=?,first_views=COALESCE(?,first_views),
            first_observed=COALESCE(?,first_observed),checked_at=?,error_type=?,evidence_json=?
            WHERE media_id=?''', (status, views, observed, time.time(), error,
            json.dumps(evidence or {}, ensure_ascii=False), media_id))


def _identity(graph, row):
    # Meta's publication timestamp precedes the local publish response; allow
    # a bounded delay while still verifying media ID, owner and Reel type.
    media_id = identifier(row['media_id'])
    metadata = graph.get(media_id, params={'fields': 'id,owner,media_type,media_product_type,timestamp'})
    if (str(metadata.get('id')) != media_id or not isinstance(metadata.get('owner'), dict) or
        str(metadata['owner'].get('id')) != graph.account_id or
        metadata.get('media_type') != 'VIDEO' or metadata.get('media_product_type') != 'REELS' or
        not 0 <= row['published_at'] - moment(metadata.get('timestamp')) <= 120):
        raise InsightsError('Meta did not confirm the same owned direct Reel.')
    return metadata


def _views(graph, media_id):
    result = graph.metrics(media_id, names=('views',))
    item = result['metrics'].get('views', {})
    return count(item.get('value')) if item.get('status') == 'ok' else None, result.get('observed_at')


def _delete(graph, row, views, first_observed):
    media_id = identifier(row['media_id'])
    if time.time() >= row['published_at'] + AGE + GRACE:
        raise InsightsError('The direct Reel deletion window has expired.')
    _identity(graph, row)
    fresh, observed = _views(graph, media_id)
    if fresh is None or fresh >= MINIMUM:
        return 'kept', fresh, observed
    if graph.pressure or graph.calls >= graph.calls_limit:
        raise InsightsError('Meta request pressure prevents a safe deletion.')
    with read_db(INSIGHTS_DB) as audit:
        proof = permission_proof(audit, graph)
    if (not proof or views is None or views >= MINIMUM or first_observed is None or
        time.time() - first_observed < GAP):
        raise InsightsError('Two fresh low-view readings at least ten minutes apart are required.')
    evidence = dict(policy='direct Reels only', threshold=MINIMUM, age_hours=2,
        media_id=media_id, account_id=graph.account_id, views=fresh,
        first_views=views, first_observed=first_observed, final_observed=observed,
        api_version=graph.version, token_sha256=hashlib.sha256(graph.token.encode()).hexdigest())
    _identity(graph, row)
    if time.time() >= row['published_at'] + AGE + GRACE:
        raise InsightsError('The direct Reel deletion window has expired.')
    _note_db = row['_db']
    _note(_note_db, media_id, 'deleting', evidence=evidence)
    request = Request(graph.base + '/' + media_id, method='DELETE', headers={
        'Accept': 'application/json', 'Authorization': 'Bearer ' + graph.token,
        'User-Agent': 'KianiExchange-DirectReelRetention/1.0'})
    graph.calls += 1
    try:
        with graph.opener.open(request, timeout=25) as response:
            graph.usage(response.headers)
            raw = response.read(8193)
        payload = json.loads(raw) if len(raw) <= 8192 else None
        if not isinstance(payload, dict) or payload.get('success') is not True:
            raise InsightsError('Meta did not confirm deletion.')
    except BaseException as exc:
        _note(_note_db, media_id, 'needs_review', views=fresh, observed=observed,
              error=type(exc).__name__, evidence=evidence)
        with _note_db:
            _set_meta(_note_db, 'paused', dict(reason='Uncertain deletion; manual review required.', media_id=media_id))
        raise InsightsError('Deletion outcome is uncertain; automatic direct Reel deletion is paused.') from None
    _note(_note_db, media_id, 'deleted', views=fresh, observed=observed, evidence=evidence)
    print('Deleted low-view direct Reel:', media_id, '| views:', fresh, flush=True)
    return 'deleted', fresh, observed


def process_due():
    """Enroll only post-activation direct Reels; review at most one due Reel per poll."""
    from instagram_trial_reels import _connect
    now = time.time()
    with _connect() as con:
        _table(con)
        enabled_after = _meta(con, 'enabled_after')
        if not isinstance(enabled_after, (int, float)) or _meta(con, 'policy_version') != 1 or _meta(con, 'paused'):
            return
        direct = con.execute('''SELECT trial_id,media_id,published_at FROM trial_reels
            WHERE reel_mode='direct' AND origin IN ('admin_direct','daily_direct')
              AND status='published' AND media_id IS NOT NULL AND published_at>=?''',
            (enabled_after,)).fetchall()
        for row in direct:
            con.execute('''INSERT OR IGNORE INTO direct_reel_retention
                (media_id,reel_id,published_at,status,checked_at) VALUES (?,?,?,'waiting',?)''',
                (row['media_id'], row['trial_id'], row['published_at'], now))
        con.commit()
        interrupted = con.execute("SELECT media_id FROM direct_reel_retention WHERE status='deleting' LIMIT 1").fetchone()
        if interrupted:
            _note(con, interrupted['media_id'], 'needs_review', error='InterruptedDelete')
            with con:
                _set_meta(con, 'paused', dict(reason='Deletion was interrupted; review before resuming.',
                                              media_id=interrupted['media_id']))
            print('Direct Reel retention paused for manual review after an interrupted delete.', flush=True)
            return
        due = con.execute('''SELECT * FROM direct_reel_retention
            WHERE (status='waiting' AND (error_type IS NULL OR checked_at<=?))
               OR (status='low_once' AND first_observed<=? AND checked_at<=?)
            ORDER BY published_at,media_id LIMIT 1''',
            (now - 300, now - GAP, now - 300)).fetchone()
        if not due:
            return
        row = dict(due)
        row['_db'] = con
        deadline = row['published_at'] + AGE + GRACE
        if now >= deadline:
            _note(con, row['media_id'], 'missed', error='AssessmentWindowExpired')
            return
        if now < row['published_at'] + AGE:
            return
        try:
            graph = Graph()
            with read_db(INSIGHTS_DB) as audit:
                permission_proof(audit, graph)
            _identity(graph, row)
            views, observed = _views(graph, row['media_id'])
            if views is None:
                _note(con, row['media_id'], 'waiting', error='ViewsUnavailable')
            elif views >= MINIMUM:
                _note(con, row['media_id'], 'kept', views=views, observed=observed,
                      evidence=dict(reason='Reached the two-hour view threshold.', views=views))
            elif row['status'] == 'waiting':
                _note(con, row['media_id'], 'low_once', views=views, observed=observed,
                      evidence=dict(reason='First low reading; awaiting a second reading.', views=views))
            else:
                result, final_views, final_observed = _delete(
                    graph, row, row['first_views'], row['first_observed'])
                if result == 'kept':
                    _note(con, row['media_id'], 'kept', views=final_views, observed=final_observed,
                          evidence=dict(reason='Final fresh reading reached threshold.', views=final_views))
        except (GraphError, InsightsError, HTTPError, URLError, TimeoutError, OSError) as exc:
            category = getattr(exc, 'category', type(exc).__name__)
            current_status = 'needs_review' if _meta(con, 'paused') else row['status']
            _note(con, row['media_id'], current_status, error=str(category)[:80])
            print('Direct Reel retention check deferred safely:', str(category)[:80], flush=True)
        finally:
            row.pop('_db', None)
