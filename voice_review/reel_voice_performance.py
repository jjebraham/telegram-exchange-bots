#!/usr/bin/env python3
"""Read-only Instagram observations and descriptive narrator comparisons."""
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import datetime
import argparse
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import time
from zoneinfo import ZoneInfo

METRICS = ('views', 'reach', 'likes', 'comments', 'saved', 'shares', 'follows')


@contextmanager
def collector_lock(directory):
    import fcntl
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = directory / 'performance.lock'
    if lock.is_symlink():
        raise ValueError('Unsafe insights lock path.')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def read_db(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The existing private database is unavailable.')
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con


def publications(path):
    with closing(read_db(path)) as con:
        columns = {row['name'] for row in con.execute('PRAGMA table_info(trial_reels)')}
        if not {'voice_json', 'duration_seconds'} <= columns:
            return []
        rows = con.execute("SELECT * FROM trial_reels WHERE status='published' AND media_id IS NOT NULL AND voice_json IS NOT NULL ORDER BY published_at DESC LIMIT 500").fetchall()
        return [dict(row) for row in rows]


def topic(row):
    title = str(row.get('title_original', '')).casefold()
    for label, pattern in (
            ('ai', r'\b(ai|artificial intelligence|chatgpt|anthropic|llm)\b'),
            ('security', r'\b(hack|hacked|exploit|breach|cyber)\w*\b'),
            ('policy', r'\b(election|tariff|sanction|regulat|federal reserve|inflation)\w*\b')):
        if re.search(pattern, title):
            return label
    return row['kind']


def stratum(row):
    dt = datetime.fromtimestamp(row['published_at'], ZoneInfo('Europe/Istanbul'))
    duration = row.get('duration_seconds')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return None
    return (topic(row), row['reel_mode'], 'short' if duration <= 30 else 'long' if duration <= 90 else 'extended',
            dt.hour // 4, dt.weekday() >= 5)


def comparison(rows, samples):
    groups, strata, seen = defaultdict(list), defaultdict(lambda: defaultdict(list)), set()
    for row in rows:
        if row['media_id'] in seen:
            continue
        seen.add(row['media_id'])
        voice = json.loads(row['voice_json'])['name']
        # Compare only measured observations in the same two-hour age window.
        choices = [s for s in samples if s['media_id'] == row['media_id'] and
                   24 <= (s['observed_at'] - row['published_at']) / 3600 <= 26]
        if not choices:
            continue
        sample = min(choices, key=lambda s: s['observed_at'])
        values = sample['metrics']
        def numeric(name):
            value = values.get(name)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
        reach = numeric('reach')
        components = [numeric(n) for n in ('likes', 'comments', 'saved', 'shares')]
        engagement = sum(components) / reach if reach and all(v is not None for v in components) else None
        item = {n: numeric(n) for n in ('views', 'reach', 'follows', 'average_watch_seconds', 'completion_rate')}
        item['engagement_rate'] = engagement
        groups[voice].append(item)
        key = stratum(row)
        if key is not None and item['views'] is not None:
            strata[key][voice].append(item['views'])
    result = []
    for voice, items in sorted(groups.items()):
        summary = {'voice': voice, 'reels_at_24_to_26_hours': len(items)}
        for name in ('views', 'reach', 'follows', 'average_watch_seconds', 'completion_rate', 'engagement_rate'):
            available = [item[name] for item in items if item[name] is not None]
            summary['median_' + name] = statistics.median(available) if available else None
            summary[name + '_available_n'] = len(available)
        result.append(summary)
    paired = []
    for key, voices in sorted(strata.items()):
        if len(voices) >= 2:
            paired.append({'topic_mode_duration_time_weekend': key,
                           'voices': {name: {'n': len(values), 'median_views': statistics.median(values)}
                                      for name, values in sorted(voices.items())}})
    return {'voices': result, 'comparable_strata': paired, 'selection_probabilities_changed': False,
            'interpretation': 'Descriptive only. Broad topic, duration, publication time, weekend and mode are grouped; creative quality and other confounders remain. Missing metrics are null, not zero. No causal winner or automatic probability change.'}


def collect(rows, graph, con, *, now=None):
    now = time.time() if now is None else now
    con.execute('''CREATE TABLE IF NOT EXISTS voice_performance(
        account_id TEXT NOT NULL, media_id TEXT NOT NULL, observed_at REAL NOT NULL,
        metrics_json TEXT NOT NULL, PRIMARY KEY(account_id,media_id,observed_at))''')
    accounts = {r[0] for r in con.execute('SELECT DISTINCT account_id FROM voice_performance')}
    if accounts and accounts != {graph.account_id}:
        raise ValueError('The performance history belongs to another Instagram account.')
    count = 0
    for row in rows:
        age = (now - row['published_at']) / 3600
        if not 24 <= age <= 26:
            continue
        old = con.execute('SELECT 1 FROM voice_performance WHERE account_id=? AND media_id=? AND observed_at BETWEEN ? AND ?',
                          (graph.account_id, row['media_id'], row['published_at'] + 24*3600, row['published_at'] + 26*3600)).fetchone()
        if old:
            continue
        response = graph.metrics(row['media_id'], names=METRICS)
        values = {n: response['metrics'].get(n, {}).get('value') for n in METRICS}
        # These stay unavailable until the account/version exposes a verified metric.
        # Average-watch-time / duration is NOT a completion rate.
        values.update(average_watch_seconds=None, completion_rate=None)
        with con:
            con.execute('INSERT INTO voice_performance VALUES(?,?,?,?)',
                        (graph.account_id, row['media_id'], response['observed_at'], json.dumps(values)))
        count += 1
        if count == 10:
            break
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--collect', action='store_true', help='GET-only Meta calls for Reels aged 24–26h; no publishing.')
    args = parser.parse_args()
    root = Path.home() / '.local/state'
    rows = publications(root / 'kiani-instagram-trial-reels/trial_reels.sqlite3')
    path = root / 'kiani-instagram-voice-review/performance.sqlite3'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Unsafe performance database path.')
    if args.collect:
        runtime = args.runtime.resolve()
        allowed = (root / 'kiani-instagram-manual-news/source').resolve()
        if runtime.parent != allowed or not re.fullmatch('[0-9a-f]{40}', runtime.name):
            raise ValueError('Expected a pinned, staged Reel runtime.')
        sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime')]
        from instagram_manual_news_intake import load_publish_env
        from instagram_insights_data import Graph
        load_publish_env()
        with collector_lock(path.parent):
            graph = Graph()
            with closing(sqlite3.connect(path)) as con:
                path.chmod(0o600)
                print('Saved observations:', collect(rows, graph, con))
    samples = []
    if path.exists():
        with closing(read_db(path)) as con:
            for row in con.execute('SELECT media_id,observed_at,metrics_json FROM voice_performance'):
                samples.append({'media_id': row['media_id'], 'observed_at': row['observed_at'], 'metrics': json.loads(row['metrics_json'])})
    print(json.dumps(comparison(rows, samples), ensure_ascii=False, indent=2))
    voices_path = root / 'kiani-instagram-voice-review/voices.sqlite3'
    if voices_path.exists():
        with closing(read_db(voices_path)) as con:
            columns = {r['name'] for r in con.execute('PRAGMA table_info(voices)')}
            status = 'rating_status' if 'rating_status' in columns else "'legacy' AS rating_status"
            opinions = [dict(r) for r in con.execute('SELECT name,score,notes,' + status + ' FROM voices WHERE voice_id IS NOT NULL')]
        print('Human opinions (separate from Instagram metrics; never selection weights):')
        print(json.dumps(opinions, ensure_ascii=False, indent=2))
    print('No publishing or deletion request was made. Voice probabilities remain unchanged.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Narrator performance report stopped:', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
