#!/usr/bin/env python3
"""Measure Feed posts and apply an explicitly activated news-only retention rule."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import html
import io
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

from instagram_insights_data import (Graph, GraphError, InsightsError, KINDS, METRICS,
    RUNTIME, STATE, STORY_CONFIG, bind_account, count, database, fingerprint, identifier, inventory,
    register, set_setting, setting, story_config)

TEHRAN = ZoneInfo('Asia/Tehran')
CHECKPOINTS = (2, 12, 24, 48, 72)
LABELS = dict(rates='Exchange rates', economy='Economy news', crypto='Crypto news',
    top50='Top 50 crypto', iran_gold='Iran gold', calendar='Economic calendar', crypto_calendar='Crypto calendar')
POLICY = dict(version=2, news_categories=['crypto', 'economy'], assessment_hours=12,
    keep_at_or_above_views=400, assessment_grace_minutes=30, delete_replacements=False,
    rate_deletion=False, historical_deletion=False, automatic_ranking_changes=False)


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise InsightsError('Refusing an analytics output symlink.')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(path):
    import fcntl
    if path.is_symlink():
        raise InsightsError('Refusing an analytics lock symlink.')
    with path.open('a') as handle:
        path.chmod(0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InsightsError('Analytics collector is already running.') from None
        yield


def window(published_at, hours):
    start = published_at + hours * 3600
    return start, start + (1800 if hours in {2, 12} else 3600)


def checkpoints(con, now):
    with con:
        for post in con.execute('SELECT media_id,published_at,kind FROM posts').fetchall():
            for hours in CHECKPOINTS:
                if hours == 12 and post['kind'] not in {'crypto', 'economy'}:
                    continue
                start, end = window(post['published_at'], hours)
                con.execute('''INSERT OR IGNORE INTO checkpoints(media_id,hours,status)
                    VALUES (?,?,?)''', (post['media_id'], hours, 'missed' if now >= end else 'pending'))
                con.execute('''UPDATE checkpoints SET status='missed',error_type='CheckpointWindowMissed'
                    WHERE media_id=? AND hours=? AND status='pending' AND ? >= ?''',
                    (post['media_id'], hours, now, end))


def save_sample(con, graph, media_id, sample):
    with con:
        cur = con.execute('''INSERT INTO samples(media_id,started_at,observed_at,api_version,metrics_json,complete)
            VALUES (?,?,?,?,?,?)''', (media_id, sample['started_at'], sample['observed_at'],
            graph.version, json.dumps(sample['metrics']), int(sample['complete'])))
    return cur.lastrowid


def value(metrics, name):
    entry = metrics.get(name, {})
    return count(entry.get('value')) if entry.get('status') == 'ok' else None


def numbers(sample):
    metrics = json.loads(sample['metrics_json'])
    return {name: value(metrics, name) for name in METRICS}


def collect_due(con, graph, owned):
    now = time.time()
    checkpoints(con, now)
    pending = []
    for row in con.execute('''SELECT c.*,p.published_at FROM checkpoints c JOIN posts p USING(media_id)
        WHERE c.status='pending' AND c.next_attempt<=?''', (now,)):
        start, end = window(row['published_at'], row['hours'])
        if start <= now < end and row['media_id'] in owned:
            pending.append((end, dict(row)))
    for _, job in sorted(pending, key=lambda x: (x[0], x[1]['media_id'])):
        if graph.calls + len(METRICS) > graph.calls_limit:
            break
        start, end = window(job['published_at'], job['hours'])
        if time.time() >= end:
            continue
        try:
            sample = graph.metrics(job['media_id'])
        except GraphError as exc:
            with con:
                con.execute('''UPDATE checkpoints SET attempts=attempts+1,next_attempt=?,error_type=?
                    WHERE media_id=? AND hours=?''', (time.time() + 900, exc.category, job['media_id'], job['hours']))
            raise
        sample_id = save_sample(con, graph, job['media_id'], sample)
        in_window = start <= sample['started_at'] <= sample['observed_at'] < end
        core = all(value(sample['metrics'], name) is not None for name in ('views', 'reach'))
        status = 'collected' if in_window and core else 'pending' if time.time() < end else 'missed'
        with con:
            con.execute('''UPDATE checkpoints SET status=?,sample_id=?,attempts=attempts+1,
                next_attempt=?,error_type=? WHERE media_id=? AND hours=?''',
                (status, sample_id, time.time() + 900, None if status == 'collected' else 'IncompleteOrLate', job['media_id'], job['hours']))
        print(f'Observed {job["media_id"]}: {job["hours"]}h checkpoint, {status}.', flush=True)
    # Existing posts get an honest current observation, never a fabricated past checkpoint.
    recent = con.execute('''SELECT p.* FROM posts p WHERE p.baseline_next<=?
        AND p.baseline_attempts<3 AND p.published_at>=?
        AND NOT EXISTS (SELECT 1 FROM samples s WHERE s.media_id=p.media_id)
        ORDER BY p.published_at DESC''', (time.time(), time.time() - 30 * 86400)).fetchall()
    for post in recent:
        if post['media_id'] not in owned or graph.calls + len(METRICS) > graph.calls_limit:
            continue
        with con:
            con.execute('UPDATE posts SET baseline_attempts=baseline_attempts+1,baseline_next=? WHERE media_id=?',
                        (time.time() + 3600, post['media_id']))
        sample = graph.metrics(post['media_id'])
        save_sample(con, graph, post['media_id'], sample)


def eligible_72(con, post):
    row = con.execute('''SELECT s.* FROM checkpoints c JOIN samples s ON s.id=c.sample_id
        WHERE c.media_id=? AND c.hours=72 AND c.status='collected' ''', (post['media_id'],)).fetchone()
    if not row:
        return None
    start, end = window(post['published_at'], 72)
    if not start <= row['started_at'] <= row['observed_at'] < end or row['observed_at'] - row['started_at'] > 300:
        return None
    return row


def baseline_review(con, post, now):
    detail = dict(policy=POLICY, baseline_count=0, automatic_deletion=False)

    def finish(status, reason, **more):
        return status, dict(detail, reason=reason, **more)

    if post['manual_keep']:
        return finish('protected', 'Marked to keep by the account owner.')
    if now < post['published_at'] + 72 * 3600:
        return finish('waiting', 'Wait for the 72-hour observation before assessing performance.')
    if post['exposure'] != 'organic':
        return finish('not_comparable', 'Organic exposure is not confirmed, or the post was promoted.')
    sample = eligible_72(con, post)
    if not sample:
        return finish('insufficient_data', 'No valid observation in the 72–73 hour window; current data cannot replace it.')
    current = numbers(sample)
    if any(current[name] is None for name in METRICS):
        return finish('insufficient_data', 'One or more metrics are missing or unsupported; no low-performance flag.')
    if current['views'] < current['reach'] or current['reach'] == 0 and current['total_interactions'] > 0:
        return finish('insufficient_data', 'Metric totals appear inconsistent; wait for human review.')
    # Positive saves/shares or attributable profile activity protect useful low-view content.
    if any(current[name] > 0 for name in ('saved', 'shares', 'profile_visits', 'follows')):
        return finish('protected', 'The post generated saves, shares, profile visits or follows.', metrics=current)
    candidates = con.execute('''SELECT * FROM posts WHERE kind=? AND media_type=?
        AND exposure='organic' AND published_at<? AND published_at>=?
        ORDER BY published_at DESC''', (post['kind'], post['media_type'], post['published_at'],
                                      post['published_at'] - 90 * 86400)).fetchall()
    peers = []
    for peer in candidates:
        reference = eligible_72(con, peer)
        if not reference or reference['api_version'] != sample['api_version']:
            continue
        values = numbers(reference)
        if any(values[name] is None for name in METRICS) or not values['reach'] or values['views'] < values['reach']:
            continue
        peers.append(dict(media_id=peer['media_id'], **values,
                          interaction_rate=values['total_interactions'] / values['reach']))
        if len(peers) == 20:
            break
    detail['baseline_count'] = len(peers)
    if len(peers) < 10:
        return finish('building_baseline', 'Need at least 10 earlier organic posts of the same category/format, measured at 72 hours.', metrics=current)
    medians = {key: statistics.median(p[key] for p in peers) for key in ('views', 'reach', 'interaction_rate')}
    if medians['views'] <= 0 or medians['reach'] <= 0:
        return finish('insufficient_data', 'The comparison baseline has no usable audience totals.')
    rate = current['total_interactions'] / current['reach'] if current['reach'] else None
    no_delivery = current['views'] == current['reach'] == current['total_interactions'] == 0
    weak = (current['views'] < medians['views'] * 0.25 and
            current['reach'] < medians['reach'] * 0.25 and
            (no_delivery or rate is not None and rate <= medians['interaction_rate']))
    more = dict(metrics=current, interaction_rate=rate, baseline_medians=medians,
                baseline_media_ids=[p['media_id'] for p in peers])
    return finish('review_low_performance' if weak else 'keep',
                  'Views and reach are below 25% of comparable medians, with no stronger engagement or protected actions. Review only.' if weak else
                  'The post does not meet the conservative low-performance review rule.', **more)


def decide(con, post, now):
    """The owner's current rule supersedes the earlier advisory 72-hour proposal."""
    detail = dict(policy=POLICY, automatic_deletion_enabled=bool(setting(con, 'retention_enabled', False)))
    if post['kind'] not in {'crypto', 'economy'}:
        return 'protected_non_news', dict(detail, reason='Only crypto/economy news is eligible. Rate, gold, top 50 and calendar posts are protected.')
    if post['manual_keep'] or post['exposure'] != 'organic':
        return 'protected', dict(detail, reason='Manually protected, promoted or unclassified post.')
    job = con.execute('SELECT * FROM retention_jobs WHERE media_id=?', (post['media_id'],)).fetchone()
    if job:
        return 'news_' + job['status'], dict(detail, reason='Recorded 12-hour news policy result.', retention=dict(job))
    cutoff = setting(con, 'retention_enrolled_after')
    if cutoff is not None and post['published_at'] < cutoff:
        return 'historical_measurement_only', dict(detail, reason='Published before news retention activation; no retroactive deletion.')
    if now < post['published_at'] + 12 * 3600:
        return 'waiting_12h', dict(detail, reason='Waiting for the 12-hour news assessment.')
    checkpoint = con.execute('''SELECT s.* FROM checkpoints c JOIN samples s ON s.id=c.sample_id
        WHERE c.media_id=? AND c.hours=12 AND c.status='collected' ''', (post['media_id'],)).fetchone()
    if not checkpoint:
        return 'insufficient_data', dict(detail, reason='A valid 12-hour views observation is unavailable; keep the post.')
    views = numbers(checkpoint)['views']
    if views is None:
        return 'insufficient_data', dict(detail, reason='Views are missing, not zero; keep the post.')
    if views >= 400:
        return 'news_keep', dict(detail, reason='At least 400 views at the 12-hour check.', views=views)
    return 'below_400_at_12h', dict(detail, reason='Below the owner-selected threshold. Deletion still requires activation, fresh rechecks and verified permissions.', views=views)


def report(con, state):
    now, output = time.time(), []
    for saved in con.execute('SELECT * FROM posts ORDER BY published_at DESC LIMIT 2000').fetchall():
        post = dict(saved)
        status, detail = decide(con, post, now)
        latest = con.execute('SELECT * FROM samples WHERE media_id=? ORDER BY observed_at DESC LIMIT 1', (post['media_id'],)).fetchone()
        observed_checkpoints = []
        for checkpoint in con.execute('SELECT hours,status,sample_id,error_type FROM checkpoints WHERE media_id=? ORDER BY hours', (post['media_id'],)):
            item = dict(checkpoint)
            observation = con.execute('SELECT * FROM samples WHERE id=?', (item['sample_id'],)).fetchone() if item['sample_id'] else None
            item.update(observed_at=observation['observed_at'] if observation else None,
                        actual_age_hours=round((observation['observed_at'] - post['published_at']) / 3600, 3) if observation else None,
                        metrics=numbers(observation) if observation else {key: None for key in METRICS})
            observed_checkpoints.append(item)
        post.update(review_status=status, review=detail,
                    published_tehran=datetime.fromtimestamp(post['published_at'], TEHRAN).isoformat(),
                    latest_observed_at=latest['observed_at'] if latest else None,
                    latest_age_hours=round((latest['observed_at'] - post['published_at']) / 3600, 3) if latest else None,
                    metrics=numbers(latest) if latest else {key: None for key in METRICS},
                    checkpoints=observed_checkpoints, baseline_review=baseline_review(con, post, now),
                    observations=[dict(observed_at=s['observed_at'], actual_age_hours=round((s['observed_at'] - post['published_at']) / 3600, 3),
                        metrics=numbers(s)) for s in con.execute('SELECT * FROM samples WHERE media_id=? ORDER BY observed_at DESC LIMIT 10', (post['media_id'],))])
        with con:
            con.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?)',
                        (post['media_id'], now, status, json.dumps(detail)))
        output.append(post)
    last_run = con.execute('SELECT * FROM runs ORDER BY started_at DESC LIMIT 1').fetchone()
    summary = dict(generated_at=now, timezone='Asia/Tehran', policy=POLICY,
        retention_enabled=setting(con, 'retention_enabled', False), retention_paused=setting(con, 'retention_paused'),
        organic_declaration=setting(con, 'organic_declaration'), collector=dict(last_run) if last_run else None,
        posts=output, note='Missing metrics are null. Current observations are not reconstructed age checkpoints. Only activated news retention can delete media.')
    reports = state / 'reports'
    atomic(reports / 'latest.json', json.dumps(summary, ensure_ascii=False, indent=2).encode())
    csvfile = io.StringIO(newline='')
    fields = ('media_id', 'kind', 'published_tehran', 'title', 'exposure', 'latest_age_hours', *METRICS, 'review_status', 'permalink')
    writer = csv.DictWriter(csvfile, fields)
    writer.writeheader()
    for post in output:
        row = {key: post.get(key) for key in fields if key not in METRICS}
        row.update(post['metrics'])
        # Spreadsheet applications must not interpret news titles as formulas.
        for key, item in row.items():
            if isinstance(item, str) and item.lstrip().startswith(('=', '+', '-', '@')):
                row[key] = "'" + item
        writer.writerow(row)
    atomic(reports / 'latest.csv', csvfile.getvalue().encode('utf-8-sig'))
    points = io.StringIO(newline='')
    point_writer = csv.DictWriter(points, ('media_id', 'kind', 'checkpoint_hours', 'status', 'actual_age_hours', *METRICS))
    point_writer.writeheader()
    for post in output:
        for checkpoint in post['checkpoints']:
            point_writer.writerow(dict(media_id=post['media_id'], kind=post['kind'], checkpoint_hours=checkpoint['hours'],
                status=checkpoint['status'], actual_age_hours=checkpoint['actual_age_hours'], **checkpoint['metrics']))
    atomic(reports / 'checkpoints.csv', points.getvalue().encode('utf-8-sig'))
    rows = []
    for post in output:
        e = lambda x: html.escape(str(x), quote=True)
        title = e(post['title'] or post['media_id'])
        if post['permalink']:
            title = '<a target="_blank" rel="noreferrer" href="' + e(post['permalink']) + '">' + title + '</a>'
        cells = [e(LABELS[post['kind']]), e(post['published_tehran'][:16].replace('T', ' ')),
                 '<span dir="auto">' + title + '</span>', e(post['latest_age_hours'] if post['latest_age_hours'] is not None else '—')]
        cells.extend('—' if post['metrics'][name] is None else f'{post["metrics"][name]:,}' for name in METRICS)
        cells += [e(post['exposure']), '<b>' + e(post['review_status'].replace('_', ' ')) + '</b><small>' + e(post['review']['reason']) + '</small>']
        rows.append('<tr data-kind="' + e(post['kind']) + '">' + ''.join('<td>' + c + '</td>' for c in cells) + '</tr>')
    options = ''.join('<option value="' + key + '">' + html.escape(label) + '</option>' for key, label in LABELS.items())
    headers = ('Category', 'Posted · Tehran', 'Post', 'Observed age · hours', 'Views', 'Reach', 'Likes', 'Comments', 'Saves', 'Shares', 'Interactions', 'Profile visits', 'Follows', 'Exposure', 'Review')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kiani · Instagram performance</title><style>
body{margin:32px;font:15px system-ui;background:#edf4f0;color:#173c30}h1{font-size:30px}p{max-width:1000px;line-height:1.6}
.box{background:white;border-radius:16px;padding:24px;overflow:auto}table{border-collapse:collapse;min-width:1450px;width:100%}
th,td{text-align:left;padding:12px;border-bottom:1px solid #dfe9e3;vertical-align:top}th{font-size:12px;position:sticky;top:0;background:white}
td:nth-child(3){min-width:240px}td:last-child{min-width:230px}small{display:block;margin-top:8px;color:#586b63;line-height:1.5}a{color:#187f59}
select{padding:10px;border:1px solid #bed6c9;border-radius:8px;margin-bottom:18px}.muted{color:#586b63}[hidden]{display:none}</style>
<h1>Kiani · Instagram performance</h1><p>Private analytics report. Updated: UPDATE · Tehran.</p><p>News retention: <strong>RETENTION_STATE</strong></p>
<p>Views, reach and engagement are cumulative observations at the displayed age. Compare posts using the same age checkpoint and category.
An em dash means unavailable—not zero. Paid/unknown exposure is excluded from organic comparisons.</p>
<p><strong>News policy: keep at least 400 views; below 400 at the 12-hour assessment is eligible for deletion only when the policy is activated.</strong>
Rate, gold, top 50 and calendar posts are protected. Missing views mean keep. No automatic replacement posts are created.
Additional 72-hour comparisons are advisory analytics; they do not override the owner's news threshold.</p>
<select id="kind" aria-label="Filter category"><option value="">All categories</option>OPTIONS</select>
<div class="box"><table><thead><tr>HEADERS</tr></thead><tbody>ROWS</tbody></table></div>
<p class="muted">Existing posts discovered too late cannot supply historical 2/24/48/72-hour readings. Those checkpoints stay missed.
The report does not imply low performance when the API returns no usable data.</p>
<script>document.getElementById('kind').addEventListener('change',function(){document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!!this.value&&r.dataset.kind!==this.value)})</script></html>'''
    state_label = 'Paused for review' if setting(con, 'retention_paused') else 'Active for new news only' if setting(con, 'retention_enabled', False) else 'Disabled'
    page = page.replace('RETENTION_STATE', state_label).replace('UPDATE', datetime.fromtimestamp(now, TEHRAN).strftime('%d %b %Y %H:%M')).replace('OPTIONS', options).replace('HEADERS', ''.join('<th>' + html.escape(x) + '</th>' for x in headers)).replace('ROWS', ''.join(rows))
    atomic(reports / 'latest.html', page.encode())
    totals = {status: sum(x['review_status'] == status for x in output) for status in sorted({x['review_status'] for x in output})}
    print('Tracked Feed posts:', len(output), '| Review states:', json.dumps(totals), flush=True)
    print('Private report:', reports / 'latest.html', flush=True)
    print('Private JSON / CSV:', reports / 'latest.json', '|', reports / 'latest.csv', flush=True)
    return summary


def run(con, state, probe=False):
    graph = Graph()
    bind_account(con, graph.account_id)
    if not probe and time.time() < setting(con, 'retry_after', 0):
        print('Analytics reads deferred by API cooldown; publishing jobs are independent.')
        return report(con, state), False
    config = story_config()
    registry, health = inventory(config, time.time() - 90 * 86400)
    print('Publication source health:', json.dumps(health), flush=True)
    if not registry:
        raise InsightsError('No published automated Feed IDs were found in the existing state.')
    run_id, started = uuid.uuid4().hex, time.time()
    with con:
        con.execute('INSERT INTO runs(id,started_at,status,health_json) VALUES (?,?,?,?)',
                    (run_id, started, 'running', json.dumps(health)))
    ok, failure = False, None
    try:
        _, owned = graph.owned_media(time.time() - 30 * 86400)
        matched = register(con, registry, owned, setting(con, 'default_exposure', 'unknown'))
        if not matched:
            raise InsightsError('No recent automated posts matched the configured Meta account.')
        checkpoints(con, time.time())
        if probe:
            quota = graph.publishing_quota()
            print('Current Meta publishing quota:', json.dumps(quota), flush=True)
            # A real account/media/insights read proves access; no guessed scope list.
            recent = [row for row in con.execute('SELECT media_id,media_type FROM posts ORDER BY published_at DESC LIMIT 100') if row['media_id'] in owned]
            candidates, selected = [], set()
            for row in recent:
                if row['media_type'] not in selected:
                    selected.add(row['media_type'])
                    candidates.append(row)
            candidates += [row for row in recent if row not in candidates][:max(0, 3 - len(candidates))]
            proven, formats = [], set()
            for row in candidates[:3]:
                sample = graph.metrics(row['media_id'])
                save_sample(con, graph, row['media_id'], sample)
                supported = [name for name in METRICS if value(sample['metrics'], name) is not None]
                print('Insights access:', row['media_id'], '| returned metrics:', ', '.join(supported) or 'none', flush=True)
                print('Observed values:', json.dumps({key: value(sample['metrics'], key) for key in METRICS}), flush=True)
                if {'views', 'reach'} <= set(supported):
                    proven.append(row['media_id'])
                    formats.add(row['media_type'])
            if not proven:
                raise InsightsError('Views/reach access was not confirmed. Review instagram_manage_insights access for the existing Facebook Login token; do not share credentials.')
            set_setting(con, 'probe', dict(verified_at=time.time(), runtime_hash=fingerprint(Path(__file__).parent),
                account_id=graph.account_id, api_version=graph.version, media_ids=proven, source_health=health,
                source_config_hash=hashlib.sha256(STORY_CONFIG.read_bytes()).hexdigest(), verified_formats=sorted(formats), publishing_quota=quota))
            print('Read-only insights access confirmed; no publish/edit/delete request was sent.', flush=True)
        else:
            from instagram_news_retention import process as news_retention
            news_retention(con, graph, config, registry, owned)
            collect_due(con, graph, owned)
        set_setting(con, 'retry_after', 0)
        ok = True
    except GraphError as exc:
        failure = exc.safe()
        delay = (86400 if exc.category in {'permission', 'authentication'} else
                 3600 if exc.category in {'rate_limit', 'usage_pressure'} else 900)
        if exc.category != 'request_budget':
            set_setting(con, 'retry_after', time.time() + delay)
        print('Analytics read stopped:', json.dumps(failure), flush=True)
    except (InsightsError, OSError, ValueError, sqlite3.Error) as exc:
        failure = dict(status=type(exc).__name__)
        print('Analytics collection could not complete:', str(exc) if isinstance(exc, InsightsError) else type(exc).__name__, flush=True)
    finally:
        with con:
            con.execute('UPDATE runs SET finished_at=?,status=?,calls=?,error_json=? WHERE id=?',
                (time.time(), 'ok' if ok else 'incomplete', graph.calls, json.dumps(failure) if failure else None, run_id))
        print('Meta read requests this run:', graph.calls, flush=True)
    return report(con, state), ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--probe', action='store_true')
    actions.add_argument('--run', action='store_true')
    actions.add_argument('--report', action='store_true')
    actions.add_argument('--keep', metavar='MEDIA_ID')
    actions.add_argument('--organic', metavar='MEDIA_ID')
    actions.add_argument('--promoted', metavar='MEDIA_ID')
    parser.add_argument('--declare-organic', action='store_true', help='Account owner confirms all automated posts are organic; mark exceptions as promoted.')
    args = parser.parse_args()
    if args.declare_organic and not args.probe:
        parser.error('The account-wide organic declaration is only accepted with the initial read-only probe.')
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(STATE / 'collector.lock'):
        con = database(STATE / 'insights.sqlite3')
        try:
            if args.declare_organic:
                set_setting(con, 'organic_declaration', dict(at=time.time(), statement='Account owner confirmed all automated posts are organic.'))
                set_setting(con, 'default_exposure', 'organic')
                with con:
                    con.execute("UPDATE posts SET exposure='organic' WHERE exposure='unknown'")
            if args.keep or args.organic or args.promoted:
                media_id = identifier(args.keep or args.organic or args.promoted)
                if not con.execute('SELECT 1 FROM posts WHERE media_id=?', (media_id,)).fetchone():
                    raise InsightsError('This media ID has not been registered as an owned automated Feed post.')
                with con:
                    if args.keep:
                        con.execute('UPDATE posts SET manual_keep=1 WHERE media_id=?', (media_id,))
                    else:
                        con.execute('UPDATE posts SET exposure=? WHERE media_id=?', ('organic' if args.organic else 'promoted', media_id))
                report(con, STATE)
                return 0
            if args.report:
                report(con, STATE)
                return 0
            _, ok = run(con, STATE, args.probe)
            return 0 if ok else 1
        finally:
            con.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, InsightsError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
