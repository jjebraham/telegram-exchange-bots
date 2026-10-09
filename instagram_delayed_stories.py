"""Persistent, one-preview-per-post Story delivery, 30 minutes after Feed success.

The worker reads existing publication records. It never collects new prices/news,
changes those databases, or republishes a Story after an uncertain final request.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import unquote, urlsplit

KINDS = ('rates', 'economy', 'top50', 'crypto')
DELAY = 1800
MAX_LATENESS = 6 * 3600


def database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    con = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    con.row_factory = sqlite3.Row
    con.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stories (
            feed_id TEXT PRIMARY KEY, kind TEXT NOT NULL, image_path TEXT NOT NULL,
            discovered_at REAL NOT NULL, published_at REAL, due_at REAL,
            status TEXT NOT NULL, next_attempt REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, container_attempts INTEGER NOT NULL DEFAULT 0,
            container_id TEXT, container_created_at REAL, story_path TEXT,
            story_id TEXT, finished_at REAL, error_type TEXT);
    ''')
    return con


@contextmanager
def locked(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def local_image(config, value, kind):
    public = Path(config['public_root']).resolve()
    parsed = urlsplit(str(value))
    if parsed.scheme:
        base = urlsplit(config['public_base'].rstrip('/') + '/')
        if (parsed.scheme != 'https' or parsed.netloc != base.netloc or
                parsed.query or parsed.fragment or not parsed.path.startswith(base.path)):
            raise ValueError('Feed image is outside the configured public media directory')
        path = public / unquote(parsed.path[len(base.path):])
    else:
        path = Path(value)
        if not path.is_absolute():
            path = public / {'crypto': 'news'}.get(kind, kind) / path
    path = path.resolve()
    if not path.is_relative_to(public) or path.suffix.lower() not in ('.jpg', '.jpeg'):
        raise ValueError('Feed image is outside the configured public JPEG directory')
    return str(path)


def published_records(config, cutoff):
    """Read-only adapters for the already-installed publishers and their schemas."""
    for kind in KINDS:
        source = Path(config['sources'][kind])
        if not source.is_file():
            print(f'Source unavailable: {kind} (missing publication state)', flush=True)
            continue
        try:
            if kind == 'rates':
                state = json.loads(source.read_text(encoding='utf-8'))
                if state.get('mode') != 'feed':
                    raise ValueError('Expected Feed state')
                images = state.get('image_urls') or [state.get('image_url')]
                rows = [(state.get('media_id'), images)]
            else:
                table = 'top50_publications' if kind == 'top50' else 'instagram_news_publications'
                saved = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
                try:
                    data = saved.execute(f'''SELECT media_id,manifest_json FROM {table}
                        WHERE status='published' AND finished_at>=?
                        ORDER BY finished_at DESC LIMIT 1000''', (cutoff,)).fetchall()
                finally:
                    saved.close()
                rows = []
                for media_id, manifest_json in data:
                    manifest = json.loads(manifest_json)
                    rows.append((media_id, manifest.get('images') or manifest.get('slides')))
            for media_id, images in rows:
                if not re.fullmatch(r'\d+', str(media_id or '')) or not images or not images[0]:
                    raise ValueError('Publication has no numeric media ID or image')
                yield str(media_id), kind, local_image(config, images[0], kind)
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError) as exc:
            print(f'Source unavailable: {kind} ({type(exc).__name__})', flush=True)


def initialize(con, config):
    """Baseline old Feed posts; activation never sends historical Stories."""
    if con.execute("SELECT 1 FROM settings WHERE key='activated_at'").fetchone():
        return
    now = time.time()
    records = list(published_records(config, 0))
    with con:
        con.execute("INSERT INTO settings VALUES ('activated_at',?)", (str(now),))
        for feed_id, kind, image in records:
            con.execute('''INSERT OR IGNORE INTO stories
                (feed_id,kind,image_path,discovered_at,status) VALUES (?,?,?,?,'baseline')''',
                        (feed_id, kind, image, now))


def scan(con, config):
    row = con.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone()
    if not row:
        raise ValueError('Initialize the Story queue before enabling delivery')
    now, cutoff = time.time(), float(row[0])
    with con:
        for feed_id, kind, image in published_records(config, cutoff):
            cur = con.execute('''INSERT OR IGNORE INTO stories
                (feed_id,kind,image_path,discovered_at,status) VALUES (?,?,?,?,'discovered')''',
                              (feed_id, kind, image, now))
            if cur.rowcount:
                print(f'Discovered successful {kind} Feed post {feed_id}', flush=True)


def load_graph(root):
    path = Path(root) / 'instagram_daily_rates.py'
    spec = importlib.util.spec_from_file_location('kiani_story_graph', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def update(con, feed_id, **values):
    with con:
        con.execute('UPDATE stories SET ' + ','.join(key + '=?' for key in values) + ' WHERE feed_id=?',
                    (*values.values(), feed_id))


def quota_available(graph):
    response = graph._graph_request('/content_publishing_limit', 'GET', {'fields': 'quota_usage,config'})
    data = response.get('data')
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError('Publishing quota response is unavailable')
    usage, config = data[0].get('quota_usage'), data[0].get('config')
    if not isinstance(config, dict):
        raise ValueError('Publishing quota configuration is unavailable')
    total = config.get('quota_total')
    if isinstance(usage, bool) or isinstance(total, bool) or not isinstance(usage, int) or not isinstance(total, int):
        raise ValueError('Publishing quota values are unavailable')
    return 0 <= usage < total


def process(con, config, graph):
    now = time.time()
    # A crash after the final request started can mean the Story went live.
    # Keep that job for review rather than risk sending it twice.
    with con:
        con.execute("UPDATE stories SET status='needs_review',error_type='InterruptedPublish' WHERE status='publishing'")
    rows = con.execute('''SELECT * FROM stories WHERE status IN ('discovered','queued','processing')
        AND next_attempt<=? ORDER BY COALESCE(due_at,discovered_at) LIMIT 12''', (now,)).fetchall()
    cutoff = float(con.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone()[0])
    for saved in rows:
        job = dict(saved)
        feed_id, status = job['feed_id'], job['status']
        try:
            if status == 'discovered':
                # Rates' old state timestamp is captured before rendering. Meta's
                # timestamp is the authoritative confirmation time for every kind.
                response = graph._graph_request('', 'GET', {'fields': 'timestamp,media_type'}, object_id=feed_id)
                if response.get('media_type') not in ('IMAGE', 'CAROUSEL_ALBUM'):
                    raise ValueError('Expected an image Feed post')
                when = datetime.fromisoformat(response['timestamp'].replace('Z', '+00:00'))
                if when.tzinfo is None:
                    raise ValueError('Feed timestamp has no timezone')
                published_at = when.timestamp()
                if not math.isfinite(published_at) or published_at > time.time() + 60:
                    raise ValueError('Invalid Feed timestamp')
                if published_at < cutoff:
                    update(con, feed_id, status='baseline', finished_at=time.time())
                    continue
                update(con, feed_id, published_at=published_at, due_at=published_at + DELAY,
                       status='queued', attempts=0, next_attempt=0, error_type=None)
                print(f'Queued {job["kind"]} Story for {when + timedelta(seconds=DELAY)}', flush=True)
                continue
            # Prepare a container shortly before the deadline so processing time
            # does not add another minute or two to the requested delay.
            if status == 'queued' and time.time() < job['due_at'] - 300:
                continue
            if time.time() > job['due_at'] + MAX_LATENESS:
                update(con, feed_id, status='expired', finished_at=time.time(), error_type='TooLate')
                print(f'Story expired without publication: {job["kind"]} {feed_id}', flush=True)
                continue
            if status == 'queued':
                if job['container_attempts'] >= 3:
                    update(con, feed_id, status='failed', error_type='ContainerRetryLimit')
                    continue
                from instagram_story_renderer import render_story
                destination = Path(config['public_root']) / 'stories' / f'kiani-story-{feed_id}.jpg'
                render_story(job['image_path'], destination, config['publisher_root'], job['kind'])
                url = config['public_base'].rstrip('/') + '/stories/' + destination.name
                graph.verify_public_image(url)
                update(con, feed_id, container_attempts=job['container_attempts'] + 1)
                container = graph._create_container({'image_url': url, 'media_type': 'STORIES'})
                if not re.fullmatch(r'\d+', container):
                    raise ValueError('Invalid Story container ID')
                update(con, feed_id, status='processing', container_id=container,
                       container_created_at=time.time(), story_path=str(destination),
                       next_attempt=time.time() + 20, attempts=0, error_type=None)
                continue
            response = graph._graph_request('', 'GET', {'fields': 'status_code'}, object_id=job['container_id'])
            code = response.get('status_code')
            if code == 'IN_PROGRESS':
                if time.time() - job['container_created_at'] > 15 * 60:
                    update(con, feed_id, status='failed', error_type='ProcessingTimeout')
                else:
                    update(con, feed_id, next_attempt=time.time() + 60)
                continue
            if code in ('ERROR', 'EXPIRED'):
                update(con, feed_id, status='queued', container_id=None, next_attempt=time.time() + 300,
                       error_type='Container' + code)
                continue
            if code == 'PUBLISHED':
                update(con, feed_id, status='needs_review', error_type='UnexpectedPublishedContainer')
                continue
            if code != 'FINISHED':
                raise ValueError('Unknown Story container status')
            if time.time() < job['due_at']:
                update(con, feed_id, next_attempt=job['due_at'], error_type=None)
                continue
            if not quota_available(graph):
                update(con, feed_id, next_attempt=time.time() + 900, error_type='PublishingQuotaFull')
                print('Story deferred: Instagram publishing quota is full', flush=True)
                continue
            update(con, feed_id, status='publishing', error_type=None)
            try:
                story_id = graph._publish_container(job['container_id'])
                if not re.fullmatch(r'\d+', story_id):
                    raise ValueError('Invalid published Story ID')
                update(con, feed_id, status='published', story_id=story_id, finished_at=time.time())
                print(f'Published delayed {job["kind"]} Story (media id: {story_id})', flush=True)
            except Exception as exc:
                update(con, feed_id, status='needs_review', error_type=type(exc).__name__)
                print(f'Story final request needs review: {job["kind"]} {feed_id} ({type(exc).__name__})', flush=True)
        except Exception as exc:
            attempts = job['attempts'] + 1
            update(con, feed_id, attempts=attempts, next_attempt=time.time() + min(1800, 60 * 2 ** min(attempts, 5)),
                   error_type=type(exc).__name__, **({'status': 'failed'} if attempts >= 8 else {}))
            # Never log Graph bodies, URLs with credentials, or exception messages.
            print(f'Story deferred: {job["kind"]} {feed_id} ({type(exc).__name__})', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.local/state/kiani-instagram-stories/config.json')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--initialize', action='store_true')
    actions.add_argument('--scan-only', action='store_true')
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--run', action='store_true', help='Deliver due Stories through the official Meta API')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    with locked(Path(config['db']).with_suffix('.lock')) as acquired:
        if not acquired:
            print('Story worker already running; skipped this invocation')
            return 0
        con = database(config['db'])
        try:
            if args.initialize:
                initialize(con, config)
                print('Story queue initialized; existing Feed posts baselined')
            elif args.status:
                for row in con.execute('SELECT kind,feed_id,status,due_at,story_id,error_type FROM stories ORDER BY discovered_at DESC LIMIT 20'):
                    print(json.dumps(dict(row), ensure_ascii=False))
            else:
                scan(con, config)
                if args.run:
                    process(con, config, load_graph(config['publisher_root']))
        finally:
            con.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: Story worker could not finish ({type(exc).__name__}). No credentials logged.', file=sys.stderr)
        raise SystemExit(1)
