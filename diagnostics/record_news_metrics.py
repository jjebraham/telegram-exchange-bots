#!/usr/bin/env python3
"""Import observed Feed metrics into separate trial storage; no platform calls."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sqlite3
import time

from instagram_post_audit import publications, timestamp

COUNTS = ('views', 'reach', 'likes', 'saves', 'shares')


def read_snapshots(path, feeds, now):
    by_id = {r['media_id']: r for r in feeds if r['kind'] in {'crypto', 'economy'}}
    result = []
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {'media_id', 'observed_at', 'promotion', 'source'} <= set(reader.fieldnames):
            raise ValueError('CSV requires media_id,observed_at,promotion,source and one or more metric columns.')
        for number, item in enumerate(reader, 2):
            media_id = str(item.get('media_id', '')).strip()
            feed = by_id.get(media_id)
            observed = timestamp(item.get('observed_at'))
            posted = timestamp(feed['posted_at']) if feed else 0
            if not feed or not posted or not posted <= observed <= now:
                raise ValueError(f'Row {number}: require a known successful news Feed and an observed timestamp between posting and now.')
            metrics = {}
            for field in COUNTS:
                raw = (item.get(field) or '').strip()
                if raw and not re.fullmatch(r'\d{1,15}', raw):
                    raise ValueError(f'Row {number}: metrics must be exact nonnegative integers; no rounded K values.')
                metrics[field] = int(raw) if raw else None
            if all(value is None for value in metrics.values()):
                raise ValueError(f'Row {number}: at least one observed metric is required.')
            promotion = (item.get('promotion') or '').strip().lower()
            origin = (item.get('source') or '').strip()
            if promotion not in {'organic', 'promoted', 'unknown'} or not 1 <= len(origin) <= 120:
                raise ValueError(f'Row {number}: promotion must be organic/promoted/unknown and source must identify the observation.')
            age = (observed - posted) / 3600
            bucket = '24h' if 23 <= age <= 25 else '48h' if 47 <= age <= 49 else 'other'
            result.append(dict(feed, observed_at=observed, age_hours=age, age_bucket=bucket,
                               metrics=metrics, promotion=promotion, metric_source=origin))
    if not result:
        raise ValueError('No metric observations supplied.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    state = Path.home() / '.local/state/kiani-news-selector-trial'
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--db', type=Path, default=state / 'metrics.sqlite3')
    args = parser.parse_args()
    now = time.time()
    feeds, _ = publications(Path.home(), now - 90 * 86400)
    observations = read_snapshots(args.csv.expanduser(), feeds, now)
    path = args.db.expanduser().resolve()
    # This helper only ever creates its own observation database.
    production = Path.home() / '.local/state'
    for relative in ('kiani-instagram-news/news.sqlite3', 'kiani-instagram-economy/economy.sqlite3',
                     'kiani-instagram-top50/top50.sqlite3', 'kiani-instagram-stories/stories.sqlite3'):
        target = production / relative
        if path == target.resolve() or (path.exists() and target.exists() and path.samefile(target)):
            parser.error('Metrics storage must not be a production publication database.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS observations (
            media_id TEXT NOT NULL, observed_at REAL NOT NULL, metric_source TEXT NOT NULL,
            kind TEXT NOT NULL, posted_at TEXT NOT NULL, time_basis TEXT NOT NULL,
            age_hours REAL NOT NULL, age_bucket TEXT NOT NULL, promotion TEXT NOT NULL,
            titles_json TEXT NOT NULL, source_urls_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
            recorded_at REAL NOT NULL, PRIMARY KEY(media_id,observed_at,metric_source)
        )''')
        before = con.total_changes
        for row in observations:
            con.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row['media_id'], row['observed_at'], row['metric_source'], row['kind'], row['posted_at'],
                 row['time_basis'], row['age_hours'], row['age_bucket'], row['promotion'],
                 json.dumps(row['titles'], ensure_ascii=False), json.dumps(row['source_urls']),
                 json.dumps(row['metrics']), now))
            print(f"{row['kind']} Feed {row['media_id']}: age {row['age_hours']:.2f}h ({row['age_bucket']}), {row['promotion']}")
        print(f'New observations: {con.total_changes - before}. Stored separately: {path}')
    print('Missing metrics remain unknown. Feed and Story metrics are not merged. No platform requests made.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Metric import failed: {exc}' if isinstance(exc, ValueError) else f'Metric import failed ({type(exc).__name__}).')
        raise SystemExit(1)
