#!/usr/bin/env python3
"""Read saved Instagram publications and inspect X persistence without API calls."""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo('Europe/Istanbul')


def clock(value):
    if value is None:
        return ''
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else datetime.fromtimestamp(float(value), timezone.utc)
        if moment.tzinfo is None:
            return ''
        return moment.astimezone(ISTANBUL).isoformat(timespec='seconds')
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def timestamp(value):
    local = clock(value)
    return datetime.fromisoformat(local).timestamp() if local else 0


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def rows(path, query, parameters=()):
    if not path.is_file():
        print(f'Missing state: {path.name}', file=sys.stderr)
        return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            return [dict(row) for row in con.execute(query, parameters)]
    except (OSError, sqlite3.Error):
        print(f'Could not read publication schema: {path.name}', file=sys.stderr)
        return []


def source_url(value):
    # Only public news URLs are emitted; omit tracking and credential-like query keys.
    try:
        parts = urlsplit(str(value or ''))
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return ''
        query = [(key, value) for key, value in parse_qsl(parts.query)
                 if not key.lower().startswith('utm_') and not re.search(r'token|secret|password|key|auth|signature', key, re.I)]
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), urlencode(sorted(query)), ''))
    except ValueError:
        return ''


def record(kind, media_id, when, basis, **extra):
    if not re.fullmatch(r'\d+', str(media_id or '')):
        return None
    return dict(kind=kind, media_id=str(media_id), posted_at=clock(when),
                time_basis=basis, titles=[], source_urls=[], scores=[], slides=None, **extra)


def manifest_details(target, manifest, fallback=None):
    fallback = fallback or {}
    stories = manifest.get('stories') or [fallback]
    for story in stories:
        if not isinstance(story, dict):
            continue
        for field, value in (('titles', story.get('title_fa')), ('source_urls', source_url(story.get('source_url')))):
            if value and value not in target[field]:
                target[field].append(value)
    ranking = manifest.get('economy_ranking')
    scores = [ranking.get('score')] if isinstance(ranking, dict) else [story.get('importance_score') for story in stories if isinstance(story, dict)]
    if not any(value is not None for value in scores):
        scores = [fallback.get('importance_score')]
    for score in scores:
        if score is not None and score not in target['scores']:
            target['scores'].append(score)
    images = manifest.get('slides') or manifest.get('images')
    if isinstance(images, list):
        target['slides'] = len(images)


def publications(home, cutoff):
    state = home / '.local/state'
    feeds = {}
    for kind, relative in (('crypto', 'kiani-instagram-news/news.sqlite3'),
                           ('economy', 'kiani-instagram-economy/economy.sqlite3')):
        data = rows(state / relative, '''SELECT n.title_fa,n.source_url,n.importance_score,
            p.media_id,p.finished_at,p.manifest_json FROM instagram_news_publications p
            JOIN instagram_news n ON n.id=p.story_id
            WHERE p.status='published' AND p.finished_at>=? ORDER BY p.finished_at''', (cutoff,))
        for row in data:
            item = feeds.get(str(row['media_id'])) or record(kind, row['media_id'], row['finished_at'], 'database success')
            if item is None:
                continue
            try:
                manifest = json.loads(row['manifest_json'] or '{}')
            except ValueError:
                manifest = {}
            manifest_details(item, manifest if isinstance(manifest, dict) else {}, row)
            feeds[item['media_id']] = item
    for row in rows(state / 'kiani-instagram-top50/top50.sqlite3', '''SELECT media_id,finished_at,manifest_json
        FROM top50_publications WHERE status='published' AND finished_at>=? ORDER BY finished_at''', (cutoff,)):
        item = record('top50', row['media_id'], row['finished_at'], 'database success')
        if item:
            item['titles'] = ['Top 50 cryptocurrency prices']
            try:
                manifest_details(item, json.loads(row['manifest_json'] or '{}'))
            except ValueError:
                pass
            feeds[item['media_id']] = item
    latest = read_json(state / 'kiani-instagram-rates/feed.json', {})
    if timestamp(latest.get('posted_at')) >= cutoff:
        item = record('rates', latest.get('media_id'), latest.get('posted_at'), 'render timestamp (approximate)')
        if item:
            item['titles'] = ['Kiani customer rates']
            item['slides'] = len(latest.get('image_urls') or [latest.get('image_url')])
            feeds[item['media_id']] = item
    stories = rows(state / 'kiani-instagram-stories/stories.sqlite3', '''SELECT kind,feed_id,published_at,
        discovered_at,status,story_id,finished_at,image_path FROM stories
        WHERE discovered_at>=? OR published_at>=? OR finished_at>=?
        ORDER BY discovered_at''', (cutoff, cutoff, cutoff))
    for story in stories:
        key = str(story['feed_id'])
        when = story.get('published_at')
        if timestamp(when) >= cutoff:
            item = feeds.get(key) or record(story['kind'], key, when, 'Meta Feed timestamp')
            if item:
                item.update(posted_at=clock(when), time_basis='Meta Feed timestamp')
                if not item['titles']:
                    item['titles'] = [story['kind'] + ' Feed']
                feeds[key] = item
    return sorted(feeds.values(), key=lambda row: row['posted_at']), stories


def x_storage(home):
    """Parse source and history only. Do not import the live bot or load its env."""
    root = home / 'sub'
    script = root / 'crypto_news_bot.py'
    result = {'script_found': script.is_file()}
    try:
        tree = ast.parse(script.read_text(encoding='utf-8'))
        poster = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'TwitterPoster')
        methods = [node for node in poster.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'post_tweet']
        calls = [node for method in methods for node in ast.walk(method) if isinstance(node, ast.Call)]
        result['twitter_post_method_found'] = bool(methods)
        result['continuation_reply_support'] = any(isinstance(node, ast.Constant) and node.value == 'in_reply_to_tweet_id'
                                                  for method in methods for node in ast.walk(method))
        result['tweet_ids_in_latest_news'] = any(isinstance(node, ast.Constant) and node.value == 'tweet_ids'
                                               for method in methods for node in ast.walk(method))
        writers = {'dump', 'write_text', 'write_bytes', 'execute', 'executemany', 'save_history', 'save_cache'}
        result['direct_storage_calls_in_post_method'] = sorted({getattr(node.func, 'attr', getattr(node.func, 'id', ''))
                                                               for node in calls if getattr(node.func, 'attr', getattr(node.func, 'id', '')) in writers})
    except (OSError, ValueError, SyntaxError, StopIteration):
        result['source_inspection'] = 'unavailable'
    history = read_json(root / 'crypto_news_history.json', {})
    entries = history.get('entries', []) if isinstance(history, dict) else []
    fields = {key for item in entries if isinstance(item, dict) for key in item
              if isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_]{1,64}', key) and re.search(r'tweet|twitter|^x_', key, re.I)}
    result['history_entries'] = len(entries)
    result['x_fields_in_history'] = sorted(fields)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--csv', type=Path, help='Optional report file; publisher state is always read-only')
    args = parser.parse_args()
    if not 1 <= args.days <= 90:
        parser.error('--days must be between 1 and 90')
    home = Path.home()
    now = time.time()
    cutoff = now - args.days * 86400
    feeds, stories = publications(home, cutoff)
    print('Report time:', clock(now), '| rolling days:', args.days)
    print('\nSUCCESSFUL FEED POSTS (Istanbul time):')
    for item in feeds:
        print(json.dumps(item, ensure_ascii=False))
    print('\nSUCCESSFUL STORIES (separate from Feed):')
    successful_stories = []
    for item in stories:
        if item['status'] == 'published' and timestamp(item.get('finished_at')) >= cutoff:
            row = dict(kind=item['kind'], media_id=str(item['story_id']),
                       posted_at=clock(item['finished_at']), time_basis='database success',
                       parent_feed_id=str(item['feed_id']))
            successful_stories.append(row)
            print(json.dumps(row, ensure_ascii=False))
    baseline = sum(item['status'] == 'baseline' and not item.get('published_at') for item in stories)
    print('\nSUMMARY:', json.dumps({'feeds': len(feeds), 'stories': len(successful_stories),
                                    'baselined_feed_records_without_saved_Meta_time': baseline}))
    print('Unpublished render manifests and failed/uncertain attempts are not counted as posted.')
    print('Historical rates state is overwritten; its earlier dates are recovered only where the Story worker saved Meta timestamps.')
    print('\nX STORAGE CHECK:', json.dumps(x_storage(home)))
    if args.csv:
        destination = args.csv.expanduser().resolve()
        if destination.exists():
            parser.error('The report destination already exists; choose a new filename')
        fields = ('content_type', 'kind', 'media_id', 'parent_feed_id', 'posted_at', 'time_basis',
                  'title', 'source_urls', 'score', 'slides')
        with destination.open('x', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in feeds:
                writer.writerow(dict(content_type='Feed', kind=item['kind'], media_id=item['media_id'],
                                     posted_at=item['posted_at'], time_basis=item['time_basis'],
                                     title=' | '.join(item['titles']), source_urls=' | '.join(item['source_urls']),
                                     score=' | '.join(str(value) for value in item['scores']), slides=item['slides']))
            for item in successful_stories:
                writer.writerow(dict(content_type='Story', **item))
        print('Optional CSV report:', destination)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'Post history audit failed ({type(error).__name__}); no publisher state changed.', file=sys.stderr)
        raise SystemExit(1)
