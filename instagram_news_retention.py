"""Owner-authorized 12-hour/400-view policy, restricted to new automated news.

Deletion is disabled until activation verifies real insights access and the
current token's management permission. No replacement publishing exists here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from instagram_insights_data import (GraphError, InsightsError, METRICS, count, identifier,
    moment, read_db, set_setting, setting)

NEWS = {'crypto', 'economy'}
AGE, GRACE, MINIMUM = 12 * 3600, 30 * 60, 400
NEWS_SOURCES = {
    'crypto': Path.home() / '.local/state/kiani-instagram-news/news.sqlite3',
    'economy': Path.home() / '.local/state/kiani-instagram-economy/economy.sqlite3',
}


def permission_proof(con, graph):
    proof = setting(con, 'permission_proof')
    if (not isinstance(proof, dict) or proof.get('account_id') != graph.account_id or
        proof.get('token_sha256') != hashlib.sha256(graph.token.encode()).hexdigest() or
        not {'instagram_manage_insights', 'instagram_manage_contents', 'instagram_content_publish', 'instagram_basic'} <= set(proof.get('scopes', []))):
        raise InsightsError('The current token has no verified news deletion/insights permission proof.')
    for name in ('expires_at', 'data_access_expires_at'):
        expiry = count(proof.get(name))
        if expiry is None or expiry and expiry <= time.time():
            raise InsightsError('The verified token/data-access expiry needs review.')
    return proof


def source_confirms(config, post, registry):
    """Positive news-source membership plus a hard exclusion of all rate sources."""
    if post['kind'] not in NEWS or registry.get(post['media_id']) != post['kind']:
        raise InsightsError('Only a registered crypto/economy Feed post may be removed.')
    expected = NEWS_SOURCES[post['kind']]
    configured = Path(config['sources'][post['kind']])
    if configured.resolve() != expected.resolve():
        raise InsightsError('News source path differs from the reviewed production database.')
    con = read_db(expected)
    try:
        rows = con.execute("SELECT media_id FROM instagram_news_publications WHERE media_id=? AND status='published'", (post['media_id'],)).fetchall()
        if len(rows) != 1:
            raise InsightsError('The original news publisher does not confirm this successful post.')
    finally:
        con.close()


def note(con, media_id, status, *, views=None, sample_id=None, error=None, evidence=None):
    with con:
        con.execute('''INSERT INTO retention_jobs(media_id,status,checked_at,views,sample_id,finished_at,error_type,evidence_json)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET
            status=excluded.status,checked_at=excluded.checked_at,views=excluded.views,
            sample_id=COALESCE(excluded.sample_id,retention_jobs.sample_id),
            finished_at=excluded.finished_at,error_type=excluded.error_type,evidence_json=excluded.evidence_json''',
            (media_id, status, time.time(), views, sample_id,
             time.time() if status in {'kept', 'deleted', 'held', 'needs_review', 'missed'} else None,
             error, json.dumps(evidence or {})))


def delete_news(con, graph, config, post, registry, fresh_views, first_sample_id):
    """The only DELETE path; every restriction is checked again at the boundary."""
    source_confirms(config, post, registry)
    permission_proof(con, graph)
    if not setting(con, 'retention_enabled', False) or setting(con, 'retention_paused'):
        raise InsightsError('News deletion is not active.')
    cutoff = setting(con, 'retention_enrolled_after')
    if (not isinstance(cutoff, (int, float)) or post['published_at'] < cutoff or
        post['manual_keep'] or post['exposure'] != 'organic' or
        not post['published_at'] + AGE <= time.time() < post['published_at'] + AGE + GRACE):
        raise InsightsError('News post is outside the authorized deletion conditions.')
    if count(fresh_views) is None or fresh_views >= MINIMUM:
        raise InsightsError('A fresh, explicit view count below 400 is required.')
    first = con.execute('SELECT * FROM samples WHERE id=? AND media_id=?', (first_sample_id, post['media_id'])).fetchone()
    if not first:
        raise InsightsError('The earlier low-view observation is missing.')
    first_metric = json.loads(first['metrics_json']).get('views', {})
    if (first_metric.get('status') != 'ok' or count(first_metric.get('value')) is None or first_metric['value'] >= MINIMUM or
        not post['published_at'] + AGE <= first['started_at'] <= first['observed_at'] < post['published_at'] + AGE + GRACE or
        time.time() - first['observed_at'] < 600):
        raise InsightsError('Require two low-view observations at least 10 minutes apart inside the assessment window.')
    # Account membership was established by the current /account/media listing;
    # check the exact media owner, type and timestamp once more before DELETE.
    metadata = graph.get(post['media_id'], params={'fields': 'id,owner,media_type,media_product_type,timestamp'})
    if (str(metadata.get('id')) != post['media_id'] or not isinstance(metadata.get('owner'), dict) or
        str(metadata['owner'].get('id')) != graph.account_id or
        metadata.get('media_type') not in {'IMAGE', 'CAROUSEL_ALBUM'} or metadata.get('media_product_type') != 'FEED' or
        abs(moment(metadata.get('timestamp')) - post['published_at']) > 1):
        raise InsightsError('Meta did not confirm the expected owned news Feed media.')
    final = graph.metrics(post['media_id'], names=('views',))
    entry = final['metrics'].get('views', {})
    views = count(entry.get('value')) if entry.get('status') == 'ok' else None
    if views is None:
        raise InsightsError('Final views are missing; keep the news post.')
    if views >= MINIMUM:
        note(con, post['media_id'], 'kept', views=views, evidence=dict(reason='Reached threshold before final deletion.'))
        return
    if time.time() >= post['published_at'] + AGE + GRACE or graph.pressure or graph.calls >= graph.calls_limit:
        raise InsightsError('Final deletion window or request budget expired; keep the post.')
    identifier(post['media_id'])
    evidence = dict(kind=post['kind'], owner=graph.account_id, views=views,
        checked_at=final['observed_at'], rule='news only; below 400 at 12 hours',
        api_version=graph.version, replacements=False)
    evidence['first_sample_id'] = first_sample_id
    # Commit before the irreversible request. A crash/timeout can never cause a
    # blind second delete. Production publication history is never rewritten.
    note(con, post['media_id'], 'deleting', views=views, evidence=evidence)
    request = Request(graph.base + '/' + post['media_id'], method='DELETE', headers={
        'Accept': 'application/json', 'Authorization': 'Bearer ' + graph.token,
        'User-Agent': 'KianiExchange-NewsRetention/1.0'})
    graph.calls += 1
    try:
        with graph.opener.open(request, timeout=25) as response:
            graph.usage(response.headers)
            raw = response.read(8193)
        payload = json.loads(raw) if len(raw) <= 8192 else None
        if not isinstance(payload, dict) or payload.get('success') is not True:
            raise InsightsError('Deletion response did not confirm success.')
    except BaseException as exc:
        note(con, post['media_id'], 'needs_review', views=views, error=type(exc).__name__, evidence=evidence)
        set_setting(con, 'retention_paused', dict(reason='Uncertain or rejected deletion; review the post before resuming.', media_id=post['media_id']))
        raise InsightsError('News deletion requires review; no automatic retry or replacement.') from None
    note(con, post['media_id'], 'deleted', views=views, evidence=evidence)
    print('Deleted low-view news Feed:', post['kind'], post['media_id'], '| views:', views, flush=True)


def process(con, graph, config, registry, owned):
    if not setting(con, 'retention_enabled', False):
        return
    cutoff = setting(con, 'retention_enrolled_after')
    if not isinstance(cutoff, (int, float)):
        raise InsightsError('News deletion activation time is missing.')
    # An interrupted final request is unresolved, not permission to try again.
    with con:
        interrupted = con.execute("SELECT media_id FROM retention_jobs WHERE status='deleting'").fetchall()
        con.execute("UPDATE retention_jobs SET status='needs_review',error_type='InterruptedDelete' WHERE status='deleting'")
    if interrupted:
        set_setting(con, 'retention_paused', dict(reason='Interrupted deletion requires manual reconciliation.'))
    if setting(con, 'retention_paused'):
        print('News deletion paused for review; analytics collection continues.', flush=True)
        return
    try:
        permission_proof(con, graph)
    except InsightsError:
        set_setting(con, 'retention_paused', dict(reason='Current token permissions/expiry need re-verification.'))
        print('News deletion held: token permissions need verification. No post removed.', flush=True)
        return
    now = time.time()
    rows = con.execute('''SELECT p.* FROM posts p WHERE p.kind IN ('crypto','economy')
        AND p.published_at>=? AND p.published_at<=?
        AND NOT EXISTS (SELECT 1 FROM retention_jobs r WHERE r.media_id=p.media_id
            AND r.status IN ('kept','deleted','held','needs_review','missed'))
        ORDER BY p.published_at''', (cutoff, now - AGE)).fetchall()
    for saved in rows:
        post = dict(saved)
        earlier = con.execute('SELECT * FROM retention_jobs WHERE media_id=?', (post['media_id'],)).fetchone()
        second_observation = earlier is not None and earlier['status'] == 'watching'
        if graph.calls + (6 if second_observation else len(METRICS)) > graph.calls_limit or graph.pressure:
            break
        if post['manual_keep'] or post['exposure'] != 'organic':
            note(con, post['media_id'], 'held', error='ProtectedOrPromoted')
            continue
        if time.time() >= post['published_at'] + AGE + GRACE:
            note(con, post['media_id'], 'missed', error='AssessmentWindowMissed')
            continue
        if post['media_id'] not in owned:
            note(con, post['media_id'], 'held', error='OwnedMediaUnavailable')
            continue
        try:
            source_confirms(config, post, registry)
            sample = graph.metrics(post['media_id'], names=('views', 'reach') if second_observation else METRICS)
            views = sample['metrics']['views']
            reach = sample['metrics']['reach']
            if views['status'] != 'ok' or reach['status'] != 'ok' or views['value'] < reach['value']:
                raise InsightsError('Missing or inconsistent views/reach; keep the post.')
            with con:
                cur = con.execute('''INSERT INTO samples(media_id,started_at,observed_at,api_version,metrics_json,complete)
                    VALUES (?,?,?,?,?,?)''', (post['media_id'], sample['started_at'], sample['observed_at'], graph.version, json.dumps(sample['metrics']), int(sample['complete'])))
                sample_id = cur.lastrowid
                if post['published_at'] + AGE <= sample['started_at'] <= sample['observed_at'] < post['published_at'] + AGE + GRACE:
                    con.execute("UPDATE checkpoints SET status='collected',sample_id=?,attempts=attempts+1,error_type=NULL WHERE media_id=? AND hours=12 AND status!='collected'", (sample_id, post['media_id']))
            if views['value'] >= MINIMUM:
                note(con, post['media_id'], 'kept', views=views['value'], sample_id=sample_id)
            else:
                if not earlier or earlier['status'] != 'watching':
                    note(con, post['media_id'], 'watching', views=views['value'], sample_id=sample_id,
                         evidence=dict(reason='First low-view observation; require another scheduled check.'))
                    continue
                if time.time() - earlier['checked_at'] < 600:
                    continue
                note(con, post['media_id'], 'checking', views=views['value'], sample_id=sample_id)
                delete_news(con, graph, config, post, registry, views['value'], earlier['sample_id'])
        except GraphError:
            raise  # Transient/read failures defer under the collector's cooldown.
        except InsightsError as exc:
            if not setting(con, 'retention_paused'):
                note(con, post['media_id'], 'held', error=type(exc).__name__)
            print('News post kept for review:', post['media_id'], '|', str(exc), flush=True)
        if setting(con, 'retention_paused'):
            break
