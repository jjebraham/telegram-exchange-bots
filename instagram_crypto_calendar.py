#!/usr/bin/env python3
"""Weekly Friday 18:00 Tehran crypto calendar, preview-first deployment."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

from crypto_calendar_data import CalendarError, TEHRAN, collect, validate, window
from instagram_crypto_calendar_renderer import caption, render

STATE = Path.home() / '.local/state/kiani-instagram-crypto-calendar'
PUBLIC = Path('/var/www/peerexo.com/public/instagram-rates')
BASE = 'https://peerexo.com/instagram-rates'
FILES = ('crypto_calendar_data.py', 'instagram_crypto_calendar.py', 'instagram_crypto_calendar_renderer.py',
         'economic_calendar_data.py', 'instagram_economic_calendar_renderer.py')
ASSETS = ('assets/instagram/kiani-logo.svg', 'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')


def fingerprint(root, names=FILES):
    return hashlib.sha256(b'\0'.join(name.encode() + b'\0' + (Path(root) / name).read_bytes()
                                    for name in names)).hexdigest()


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CalendarError('Another weekly calendar publisher is active.') from None
        yield


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    con = sqlite3.connect(path, timeout=15)
    os.chmod(path, 0o600)
    con.row_factory = sqlite3.Row
    con.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS calendar_previews (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, runtime_hash TEXT NOT NULL,
            assets_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, manifest_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS instagram_news_publications (
            week_key TEXT PRIMARY KEY, status TEXT NOT NULL, started_at REAL NOT NULL,
            finished_at REAL, container_id TEXT, media_id TEXT, manifest_json TEXT NOT NULL,
            error_type TEXT);
    ''')
    return con


def already(con, week):
    row = con.execute('SELECT status,media_id FROM instagram_news_publications WHERE week_key=?', (week,)).fetchone()
    if row and row['status'] == 'published':
        print('Already published this Tehran week:', row['media_id'])
        return True
    if row and row['status'] in {'preparing', 'publishing', 'needs_review'}:
        raise CalendarError('Earlier calendar attempt requires review before retry; no duplicate post created.')
    return False


def helper(root):
    spec = importlib.util.spec_from_file_location('kiani_crypto_calendar_graph', root / 'instagram_daily_rates.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def publish(con, snapshot, manifest, assets):
    validate(snapshot, publishing=True)
    week = datetime.fromisoformat(snapshot['window_start']).astimezone(TEHRAN).date().isoformat()
    if already(con, week):
        return
    if not os.getenv('INSTAGRAM_USER_ID') or not os.getenv('INSTAGRAM_ACCESS_TOKEN'):
        raise CalendarError('The existing private Instagram configuration is not loaded.')
    graph = helper(assets)
    urls = manifest['image_urls']
    for url in urls:
        graph.verify_public_image(url)
    with con:
        con.execute('''INSERT INTO instagram_news_publications
            (week_key,status,started_at,manifest_json) VALUES (?,'preparing',?,?)
            ON CONFLICT(week_key) DO UPDATE SET status='preparing',started_at=excluded.started_at,
            finished_at=NULL,container_id=NULL,media_id=NULL,manifest_json=excluded.manifest_json,error_type=NULL''',
                    (week, time.time(), json.dumps(manifest, ensure_ascii=False)))
    final_started = False
    try:
        if len(urls) == 1:
            parent = graph._create_container({'image_url': urls[0], 'caption': manifest['caption']})
        else:
            children = []
            for url in urls:
                child = graph._create_container({'image_url': url, 'is_carousel_item': 'true'})
                graph._wait_for_container(child)
                children.append(child)
            parent = graph._create_container({'media_type': 'CAROUSEL', 'children': ','.join(children),
                                               'caption': manifest['caption']})
        if not re.fullmatch(r'\d+', str(parent)):
            raise CalendarError('Invalid calendar media container ID.')
        with con:
            con.execute('UPDATE instagram_news_publications SET container_id=? WHERE week_key=?', (parent, week))
        graph._wait_for_container(parent)
        validate(snapshot, publishing=True)
        with con:
            con.execute("UPDATE instagram_news_publications SET status='publishing' WHERE week_key=?", (week,))
        final_started = True
        media = graph._publish_container(parent)
        if not re.fullmatch(r'\d+', str(media)):
            raise CalendarError('Invalid published calendar media ID.')
        with con:
            con.execute("UPDATE instagram_news_publications SET status='published',media_id=?,finished_at=? WHERE week_key=?",
                        (media, time.time(), week))
        print(f'Published weekly crypto calendar ({len(urls)} slides, media id: {media}).')
    except BaseException as exc:
        with con:
            con.execute('UPDATE instagram_news_publications SET status=?,finished_at=?,error_type=? WHERE week_key=?',
                        ('needs_review' if final_started else 'failed', time.time(), type(exc).__name__, week))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--asset-root', type=Path, default=Path.home() / 'kiani-instagram-publisher')
    parser.add_argument('--state', type=Path, default=STATE)
    args = parser.parse_args()
    os.umask(0o077)
    now = datetime.now(TEHRAN)
    start, end = window(now)
    if args.publish and not start <= now < start + timedelta(hours=2):
        raise CalendarError('Publishing is allowed Friday 18:00–20:00 Tehran only.')
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(args.state / ('publication.lock' if args.publish else 'preview.lock')):
        con = database(args.state / 'calendar.sqlite3')
        try:
            if args.status:
                for row in con.execute('SELECT week_key,status,media_id,finished_at,error_type FROM instagram_news_publications ORDER BY week_key DESC LIMIT 8'):
                    print(json.dumps(dict(row)))
                return 0
            if args.publish and already(con, start.date().isoformat()):
                return 0
            folder = args.state / 'runs' / (now.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
            folder.mkdir(parents=True, mode=0o700)
            print('Calendar window:', start.isoformat(), 'to', end.isoformat(), flush=True)
            try:
                snapshot = collect(start, end)
            except CalendarError as exc:
                report = dict(status='failed', generated_at=now.isoformat(), error=str(exc),
                              sources=getattr(exc, 'health', {}))
                (folder / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print('Official source health:', json.dumps(report['sources']), flush=True)
                raise
            validate(snapshot)
            segment = 'crypto-calendar' if args.publish else 'crypto-calendar-preview'
            output = PUBLIC / segment
            output.mkdir(parents=True, exist_ok=True, mode=0o755)
            output.chmod(0o755)
            paths = render(snapshot, output, args.asset_root, preview=not args.publish)
            text = caption(snapshot, args.asset_root)
            if len(text) > 2200:
                raise CalendarError('Calendar caption exceeds Instagram caption capacity.')
            manifest = dict(kind='crypto_calendar', images=paths, image_urls=[BASE + '/' + segment + '/' + Path(p).name for p in paths],
                            caption=text, generated_at=snapshot['generated_at'], window_start=snapshot['window_start'],
                            window_end=snapshot['window_end'], timezone='Asia/Tehran')
            audit = dict(status='prepared' if args.publish else 'previewed', snapshot=snapshot, manifest=manifest)
            (folder / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
            for row in snapshot['events']:
                print(row['tehran'] or (row['tehran_date'] + ' (date estimate; no clock)'), row['title_fa'], '|', row['source_url'], flush=True)
            for url in manifest['image_urls']:
                print('Crypto calendar slide:', url, flush=True)
            if args.publish:
                publish(con, snapshot, manifest, args.asset_root)
            else:
                with con:
                    con.execute('INSERT INTO calendar_previews VALUES (?,?,?,?,?,?)',
                                (folder.name, time.time(), fingerprint(Path(__file__).parent), fingerprint(args.asset_root, ASSETS),
                                 json.dumps(snapshot, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False)))
                print('Preview complete. No Instagram API contact and no schedule activated.')
            print('Private audit:', folder / 'audit.json', flush=True)
        finally:
            con.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: ' + (str(exc) if isinstance(exc, CalendarError) else type(exc).__name__), file=sys.stderr)
        raise SystemExit(1)
