#!/usr/bin/env python3
"""Import successful Telegram news into an independent Instagram SQLite queue."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

UTC = timezone.utc


class NewsError(RuntimeError):
    pass


def canonical_url(url):
    parts = urlsplit(str(url).strip())
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise NewsError('A news item needs a public HTTP(S) source URL.')
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), urlencode(sorted(query)), ''))


def clean_text(value):
    text = str(value or '')
    text = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def timestamp(value):
    if isinstance(value, bool):
        raise NewsError('Invalid news timestamp.')
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NewsError('Invalid news timestamp.') from exc
    if not math.isfinite(result) or result <= 0:
        raise NewsError('Invalid news timestamp.')
    return result


def importance(title, summary):
    """A documented editorial heuristic, not an assertion of objective importance."""
    text = (title + ' ' + summary).lower()
    groups = (
        (40, 'security', ('hack', 'exploit', 'kidnap', 'extortion', 'violent', 'breach', 'هک', 'آدم‌ربایی', 'اخاذی', 'سرقت', 'امنیت')),
        (35, 'regulation', ('sanction', 'regulat', 'court', 'government', 'sec ', 'lawmakers', 'تحریم', 'قانون', 'دولت', 'دادگاه')),
        (25, 'market', ('etf', 'liquidation', 'outflow', 'inflow', 'crash', 'bitcoin', 'ethereum', 'بیت‌کوین', 'اتریوم', 'لیکویید', 'صندوق')),
        (15, 'industry', ('exchange', 'stablecoin', 'bank', 'صرافی', 'استیبل', 'بانک')),
    )
    matches = [(weight, name) for weight, name, words in groups if any(word in text for word in words)]
    return sum(weight for weight, _ in matches), [name for _, name in matches]


def read_json(path):
    # These legacy files are written in place; retry an incomplete concurrent write.
    for attempt in range(3):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            if attempt == 2:
                raise NewsError(f'Incomplete news JSON; retry after its writer finishes: {Path(path).name}')
            time.sleep(0.1)
        except OSError as exc:
            raise NewsError(f'Could not read news input: {Path(path).name}') from exc


@contextmanager
def database(path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
            CREATE TABLE IF NOT EXISTS instagram_news (
                id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE,
                title_original TEXT NOT NULL, title_fa TEXT NOT NULL,
                summary_fa TEXT NOT NULL, telegram_posted_at REAL,
                article_date TEXT, source_name TEXT NOT NULL,
                image_url TEXT, highlights_json TEXT NOT NULL DEFAULT '[]',
                importance_score INTEGER NOT NULL, importance_reasons TEXT NOT NULL,
                origin TEXT NOT NULL CHECK(origin IN ('telegram','manual')),
                imported_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS instagram_news_publications (
                story_id TEXT PRIMARY KEY REFERENCES instagram_news(id),
                run_id TEXT NOT NULL, status TEXT NOT NULL,
                started_at REAL NOT NULL, finished_at REAL,
                container_id TEXT, media_id TEXT, manifest_json TEXT,
                error_type TEXT
            );
            CREATE INDEX IF NOT EXISTS instagram_news_fresh ON instagram_news(telegram_posted_at);
        ''')
        yield con
    finally:
        con.close()


def save_story(con, story, now=None):
    now = time.time() if now is None else now
    url = canonical_url(story['source_url'])
    title, summary = clean_text(story['title_fa']), clean_text(story['summary_fa'])
    if not title or not summary or not re.search(r'[\u0600-\u06ff]', title + summary):
        raise NewsError('A news item needs its existing Persian title and summary.')
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    score, reasons = importance(clean_text(story.get('title_original', '')), title + ' ' + summary)
    values = (key, url, clean_text(story.get('title_original', '')), title, summary,
              story.get('telegram_posted_at'), story.get('article_date'),
              story.get('source_name') or urlsplit(url).hostname,
              story.get('image_url'), json.dumps(story.get('highlights', []), ensure_ascii=False),
              score, json.dumps(reasons), story.get('origin', 'telegram'), now)
    with con:
        con.execute('''INSERT INTO instagram_news VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_url) DO UPDATE SET
              title_original=excluded.title_original, title_fa=excluded.title_fa,
              summary_fa=excluded.summary_fa,
              telegram_posted_at=COALESCE(excluded.telegram_posted_at,instagram_news.telegram_posted_at),
              importance_score=excluded.importance_score,
              importance_reasons=excluded.importance_reasons,
              article_date=COALESCE(excluded.article_date,instagram_news.article_date),
              image_url=COALESCE(excluded.image_url,instagram_news.image_url),
              source_name=CASE WHEN excluded.image_url IS NOT NULL THEN excluded.source_name ELSE instagram_news.source_name END,
              highlights_json=CASE WHEN excluded.highlights_json!='[]' THEN excluded.highlights_json ELSE instagram_news.highlights_json END,
              origin=CASE WHEN excluded.origin='telegram' THEN 'telegram' ELSE instagram_news.origin END
        ''', values)
    return key


def sync_telegram(con, source_dir, now=None):
    now = time.time() if now is None else now
    source_dir = Path(source_dir).expanduser()
    history = read_json(source_dir / 'crypto_news_history.json')
    translations = read_json(source_dir / 'translation_cache.json')
    if not isinstance(history, dict) or not isinstance(history.get('entries'), list) or not isinstance(translations, dict):
        raise NewsError('The Telegram news history/cache schema changed.')
    counts = {'imported': 0, 'outside_window': 0, 'missing_translation': 0, 'invalid': 0}
    for entry in history['entries']:
        try:
            posted = timestamp(entry['timestamp'])
            if not now - 86400 <= posted <= now:
                counts['outside_window'] += 1
                continue
            original = str(entry['title'])
            # The cache key is title:content_start; titles can themselves contain colons.
            candidates = []
            for key, value in translations.items():
                if not str(key).startswith(original + ':') or not isinstance(value, dict):
                    continue
                try:
                    cached = timestamp(value.get('timestamp'))
                except NewsError:
                    continue
                if cached <= posted + 120 and value.get('title') and value.get('summary'):
                    candidates.append((cached, str(key), value))
            if not candidates:
                counts['missing_translation'] += 1
                continue
            translated = max(candidates, key=lambda row: (row[0], row[1]))[2]
            save_story(con, {'source_url': entry['url'], 'title_original': original,
                            'title_fa': translated['title'], 'summary_fa': translated['summary'],
                            'telegram_posted_at': posted, 'origin': 'telegram'}, now)
            counts['imported'] += 1
        except (KeyError, TypeError, ValueError, NewsError):
            counts['invalid'] += 1
    return counts


def select_stories(con, limit=1, now=None, source_url=None):
    now = time.time() if now is None else now
    if source_url:
        rows = con.execute('SELECT * FROM instagram_news WHERE source_url=?', (canonical_url(source_url),)).fetchall()
    else:
        rows = con.execute('''SELECT n.* FROM instagram_news n
            LEFT JOIN instagram_news_publications p ON n.id=p.story_id
            WHERE n.origin='telegram' AND n.telegram_posted_at BETWEEN ? AND ?
              AND (p.story_id IS NULL OR p.status='failed')
            ORDER BY n.importance_score DESC, n.telegram_posted_at DESC, n.source_url ASC LIMIT ?
        ''', (now - 86400, now, limit)).fetchall()
    return [dict(row) for row in rows]


def claim(con, stories, run_id, manifest):
    con.execute('BEGIN IMMEDIATE')
    try:
        for story in stories:
            previous = con.execute('SELECT status FROM instagram_news_publications WHERE story_id=?', (story['id'],)).fetchone()
            if previous and previous['status'] != 'failed':
                raise NewsError('This story is already published or has an unresolved publish attempt; inspect its status.')
            con.execute('''INSERT INTO instagram_news_publications
                (story_id,run_id,status,started_at,manifest_json) VALUES (?,?,'publishing',?,?)
                ON CONFLICT(story_id) DO UPDATE SET run_id=excluded.run_id,status='publishing',
                  started_at=excluded.started_at,finished_at=NULL,container_id=NULL,media_id=NULL,
                  manifest_json=excluded.manifest_json,error_type=NULL''',
                (story['id'], run_id, time.time(), json.dumps(manifest, ensure_ascii=False)))
        con.commit()
    except BaseException:
        con.rollback()
        raise


def publish(con, stories, paths, caption, ig, manifest):
    urls = [ig._public_image_url(path) for path in paths]
    for url in urls:
        ig.verify_public_image(url)
    run_id = uuid.uuid4().hex
    claim(con, stories, run_id, manifest)
    publishing_started = False
    try:
        if len(urls) == 1:
            container = ig._create_container({'image_url': urls[0], 'caption': caption})
            ig._wait_for_container(container)
        else:
            children = []
            for url in urls:
                child = ig._create_container({'image_url': url, 'is_carousel_item': 'true'})
                ig._wait_for_container(child)
                children.append(child)
            container = ig._create_container({'media_type': 'CAROUSEL', 'children': ','.join(children), 'caption': caption})
            ig._wait_for_container(container)
        with con:
            con.execute('UPDATE instagram_news_publications SET container_id=? WHERE run_id=?', (container, run_id))
        publishing_started = True
        media_id = ig._publish_container(container)
        with con:
            con.execute("UPDATE instagram_news_publications SET status='published',finished_at=?,media_id=? WHERE run_id=?",
                        (time.time(), media_id, run_id))
        return media_id
    except Exception as exc:
        with con:
            con.execute('UPDATE instagram_news_publications SET status=?,finished_at=?,error_type=? WHERE run_id=?',
                        ('needs_review' if publishing_started else 'failed', time.time(), type(exc).__name__, run_id))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--db', type=Path, default=Path.home() / '.local/state/kiani-instagram-news/news.sqlite3')
    parser.add_argument('--story-json', type=Path, help='An explicitly chosen manual story; excluded from automatic selection')
    parser.add_argument('--url', help='Select an imported story explicitly for manual testing')
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--output', type=Path, default=Path('/var/www/peerexo.com/public/instagram-rates/news'))
    parser.add_argument('--public-base', default='https://peerexo.com/instagram-rates/news')
    parser.add_argument('--publisher-root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--sync-only', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 5:
        parser.error('--limit must be between 1 and 5')
    if args.publish and (args.dry_run or args.sync_only or args.status):
        parser.error('--publish cannot be combined with a preview/status action')
    with database(args.db) as con:
        if args.status:
            for row in con.execute('SELECT n.id,n.title_fa,p.status,p.media_id,p.container_id FROM instagram_news n LEFT JOIN instagram_news_publications p ON n.id=p.story_id ORDER BY n.imported_at DESC LIMIT 10'):
                print(json.dumps(dict(row), ensure_ascii=False))
            return 0
        if args.source_dir:
            print('Telegram import:', json.dumps(sync_telegram(con, args.source_dir), ensure_ascii=False))
        if args.sync_only:
            if not args.source_dir:
                parser.error('--sync-only requires --source-dir')
            return 0
        chosen_url = args.url
        if args.story_json:
            story = read_json(args.story_json)
            story['origin'] = 'manual'
            save_story(con, story)
            chosen_url = story['source_url']
        stories = select_stories(con, args.limit, source_url=chosen_url)
        if not stories:
            raise NewsError('No unpublished Persian Telegram news in the last 24 hours. Import the source history/cache first.')
        for story in stories:
            print(f"Selected [{story['id']}] score={story['importance_score']}: {story['title_fa']}")
        from instagram_news_renderer import render_news
        paths, caption, manifest = render_news(stories, args.output, args.publisher_root)
        for path in paths:
            print('News slide:', path)
        print(caption)
        if not args.publish:
            print('Preview complete; Instagram was not contacted.')
            return 0
        if not 1 <= len(paths) <= 10:
            raise NewsError('An Instagram news post must contain 1–10 slides.')
        if not chosen_url and any(story['telegram_posted_at'] < time.time() - 86400 for story in stories):
            raise NewsError('A selected story expired from the 24-hour window during rendering; rerun selection.')
        sys.path.insert(0, str(args.publisher_root.resolve()))
        import instagram_daily_rates as ig
        os.environ['INSTAGRAM_PUBLIC_MEDIA_BASE_URL'] = args.public_base
        media_id = publish(con, stories, paths, caption, ig, manifest)
        print(f'Published Instagram crypto news ({len(paths)} slides, media id: {media_id})')
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Persist only error types in the database; never save credentials or raw API responses there.
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
