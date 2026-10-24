#!/usr/bin/env python3
"""Daily gainers cover plus five top 50 price slides, once per Istanbul day."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import quote, urlsplit
import uuid
from zoneinfo import ZoneInfo

from crypto_top50_data import PricesError, SnapshotExpiredError, collect, validate_snapshot
from instagram_top50_renderer import caption, render

RUNTIME_FILES = ('instagram_top50_prices.py', 'crypto_top50_data.py', 'instagram_top50_renderer.py', 'crypto_akamai_rate.py')
SHARED_FILES = ('instagram_daily_rates.py', 'assets/instagram/kiani-logo.svg',
                'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')
DEFAULT_DB = Path.home() / '.local/state/kiani-instagram-top50/top50.sqlite3'
DEFAULT_OUTPUT = Path('/var/www/peerexo.com/public/instagram-rates/top50')
DEFAULT_BASE = 'https://peerexo.com/instagram-rates/top50'
PREPARATION_ATTEMPTS = 3
UPLOAD_WORKERS = 3


def log_stage(stage, started, snapshot=None):
    """Log timing and original expiry only; never Graph errors or credentials."""
    message = f'Top 50 stage={stage} elapsed={time.monotonic() - started:.1f}s'
    evidence = (snapshot or {}).get('rate_evidence')
    if isinstance(evidence, dict) and evidence.get('valid_until_utc'):
        expiry = datetime.fromisoformat(evidence['valid_until_utc'].replace('Z', '+00:00'))
        remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
        message += f' original_expiry={expiry.isoformat()} remaining={remaining:.1f}s'
    print(message, flush=True)


def fingerprint(root, names):
    return hashlib.sha256(b'\0'.join(name.encode() + b'\0' + (root / name).read_bytes()
                                   for name in names)).hexdigest()


@contextmanager
def run_lock(db):
    lock = Path(str(db) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if lock.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PricesError('Another top 50 run is active; skipped.') from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PricesError('Another top 50 run is active; skipped.') from None
        yield


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
        CREATE TABLE IF NOT EXISTS top50_snapshots (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, created_at REAL NOT NULL,
            data_json TEXT NOT NULL, manifest_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS top50_publications (
            day TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES top50_snapshots(id),
            status TEXT NOT NULL CHECK(status IN ('publishing','published','failed','needs_review')),
            started_at REAL NOT NULL, finished_at REAL, container_id TEXT, media_id TEXT,
            manifest_json TEXT NOT NULL, error_type TEXT);
    ''')
    return con


def existing_publication(con, day):
    row = con.execute('SELECT status,media_id FROM top50_publications WHERE day=?', (day,)).fetchone()
    if row and row['status'] == 'published':
        print(f"Already published today's top 50 carousel (media id: {row['media_id']}).")
        return True
    if row and row['status'] in {'publishing', 'needs_review'}:
        raise PricesError('An earlier publication has an uncertain result. Review Instagram and the database before retrying.')
    return False


def today():
    return datetime.now(ZoneInfo('Europe/Istanbul')).date().isoformat()


def publish(con, snapshot, manifest, asset_root, public_base):
    started = time.monotonic()
    log_stage('publication_precheck', started, snapshot)
    validate_snapshot(snapshot, publishing=True)
    day = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul')).date().isoformat()
    if day != today():
        raise PricesError('The Istanbul date changed while preparing the carousel; rerun with fresh prices.')
    if existing_publication(con, day):
        return None
    if urlsplit(public_base).scheme != 'https' or not urlsplit(public_base).netloc:
        raise PricesError('The public image base must be an HTTPS URL.')
    if not os.environ.get('INSTAGRAM_USER_ID') or not os.environ.get('INSTAGRAM_ACCESS_TOKEN'):
        raise PricesError('Load the existing Instagram environment before publishing.')
    path = asset_root / 'instagram_daily_rates.py'
    spec = importlib.util.spec_from_file_location('kiani_top50_shared_publisher', path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    urls = [public_base.rstrip('/') + '/' + quote(Path(p).name) for p in manifest['images']]
    if len(urls) != 6:
        raise PricesError('Exactly six public slides are required: gainers first, then five price slides.')
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        list(pool.map(helper.verify_public_image, urls))
    log_stage('public_images_verified', started, snapshot)
    validate_snapshot(snapshot, publishing=True)
    with con:
        con.execute('BEGIN IMMEDIATE')
        if existing_publication(con, day):
            return None
        con.execute('''INSERT INTO top50_publications
            (day,snapshot_id,status,started_at,manifest_json) VALUES (?,?,'publishing',?,?)
            ON CONFLICT(day) DO UPDATE SET snapshot_id=excluded.snapshot_id,status='publishing',
            started_at=excluded.started_at,finished_at=NULL,container_id=NULL,media_id=NULL,
            manifest_json=excluded.manifest_json,error_type=NULL''',
            (day, manifest['snapshot_id'], time.time(), json.dumps(manifest, ensure_ascii=False)))
    publish_started = False
    stage = 'child_containers'
    try:
        log_stage(stage, started, snapshot)

        def prepare_child(item):
            index, url = item
            validate_snapshot(snapshot, publishing=True)
            child = helper._create_container({'image_url': url, 'is_carousel_item': 'true'})
            helper._wait_for_container(child)
            print(f'Top 50 child_ready={index}/6 elapsed={time.monotonic() - started:.1f}s', flush=True)
            return child

        # SQLite and the parent/final publish remain on the main thread.
        # Read results in slide order, and inspect every worker's result.
        # A real API/processing error takes precedence over a simultaneous
        # expiry, so it cannot be hidden by an automatic freshness retry.
        children, errors = [], []
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            futures = [pool.submit(prepare_child, item) for item in enumerate(urls, 1)]
            for future in futures:
                try:
                    children.append(future.result())
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise next((exc for exc in errors if not isinstance(exc, SnapshotExpiredError)), errors[0])
        stage = 'parent_container'
        log_stage(stage, started, snapshot)
        validate_snapshot(snapshot, publishing=True)
        parent = helper._create_container({'media_type': 'CAROUSEL', 'children': ','.join(children),
                                           'caption': manifest['caption']})
        with con:
            con.execute('UPDATE top50_publications SET container_id=? WHERE day=?', (parent, day))
        helper._wait_for_container(parent)
        stage = 'final_freshness_check'
        log_stage(stage, started, snapshot)
        validate_snapshot(snapshot, publishing=True)
        if day != today():
            raise PricesError('The Istanbul date changed before publication; rerun with fresh prices.')
        # A timeout after this point may mean Meta published it. Never retry blindly.
        stage = 'final_publish_request'
        publish_started = True
        media_id = helper._publish_container(parent)
        with con:
            con.execute("UPDATE top50_publications SET status='published',media_id=?,finished_at=? WHERE day=?",
                        (media_id, time.time(), day))
        print(f'Published Kiani top 50 cryptocurrency carousel (6 slides, gainers first, media id: {media_id})')
        log_stage('published', started, snapshot)
        return media_id
    except BaseException as exc:
        print(f'Top 50 failed_stage={stage} error_type={type(exc).__name__} '
              f'final_publish_started={publish_started}', flush=True)
        with con:
            con.execute('UPDATE top50_publications SET status=?,finished_at=?,error_type=? WHERE day=?',
                        ('needs_review' if publish_started else 'failed', time.time(), type(exc).__name__, day))
        raise


def prepare_carousel(con, snapshot, output, root):
    started = time.monotonic()
    log_stage('render_start', started, snapshot)
    paths = render(snapshot, output, root)
    log_stage('render_complete', started, snapshot)
    manifest = dict(snapshot_id=uuid.uuid4().hex, images=[str(p) for p in paths],
                    caption=caption(snapshot), generated_at=snapshot['generated_at'],
                    sample=bool(snapshot.get('sample')),
                    top50_runtime_fingerprint=fingerprint(Path(__file__).resolve().parent, RUNTIME_FILES),
                    shared_assets_fingerprint=fingerprint(root, SHARED_FILES))
    if snapshot.get('schema') == 3:
        manifest['sections'] = ['gainers'] + ['top50'] * 5
    day = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul')).date().isoformat()
    with con:
        con.execute('INSERT INTO top50_snapshots VALUES (?,?,?,?,?)',
                    (manifest['snapshot_id'], day, time.time(),
                     json.dumps(snapshot, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False)))
    manifest_path = output / (paths[0].name.removesuffix('-01.jpg') + '.json')
    manifest_path.write_text(json.dumps(dict(manifest, snapshot=snapshot), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"USDT market rate: {snapshot['usdt_toman']} Toman | {snapshot['rate_source']}")
    for index, path in enumerate(paths, 1):
        print(f'Top 50 slide {index}/{len(paths)}: {path}')
    if snapshot.get('schema') == 3:
        print('24h gainers from top 100:', json.dumps([dict(symbol=c['symbol'],
            change_24h=c['change_24h'], market_position=c['market_position']) for c in snapshot['gainers']]), flush=True)
    print(manifest['caption'])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Publish fresh prices; default is preview only')
    parser.add_argument('--sample-json', type=Path, help='Render a saved reference snapshot; never publish it')
    parser.add_argument('--status', action='store_true', help='Show publication history without fetching prices')
    parser.add_argument('--publisher-root', type=Path, default=Path.home() / 'kiani-instagram-publisher')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--public-base', default=DEFAULT_BASE)
    args = parser.parse_args()
    if args.sample_json and args.publish:
        raise PricesError('Reference snapshots are preview-only; remove --sample-json to publish fresh prices.')
    if args.status and args.publish:
        raise PricesError('Choose status or publication.')
    db, root, output = args.db.expanduser().resolve(), args.publisher_root.expanduser().resolve(), args.output.expanduser().resolve()
    with run_lock(db), database(db) as con:
        if args.status:
            for row in con.execute('SELECT day,status,media_id,error_type FROM top50_publications ORDER BY day DESC LIMIT 10'):
                print(dict(row))
            return 0
        run_day = today()
        attempts = PREPARATION_ATTEMPTS if args.publish else 1
        for attempt in range(1, attempts + 1):
            if args.publish:
                if today() != run_day:
                    raise PricesError('The Istanbul date changed; no next-day catch-up attempted.')
                if existing_publication(con, run_day):
                    return 0
            started = time.monotonic()
            print(f'Top 50 preparation_attempt={attempt}/{attempts}', flush=True)
            try:
                if args.sample_json:
                    snapshot = json.loads(args.sample_json.read_text(encoding='utf-8'))
                    snapshot['sample'] = True
                else:
                    snapshot = collect()
                validate_snapshot(snapshot, publishing=not snapshot.get('sample'))
                log_stage('collection_complete', started, snapshot)
                manifest = prepare_carousel(con, snapshot, output, root)
                if args.publish:
                    publish(con, snapshot, manifest, root, args.public_base)
                else:
                    print('Preview complete; nothing published.')
                return 0
            except SnapshotExpiredError as exc:
                # Never retry a request that might have made a live Feed post.
                # Completed/uncertain decisions retain their original guard.
                if args.publish and existing_publication(con, run_day):
                    return 0
                print(f'Top 50 freshness_expired attempt={attempt}/{attempts}: {exc}', flush=True)
                if attempt == attempts:
                    raise
                print('Recollecting all prices and rebuilding six new slides; no old evidence or containers reused.', flush=True)
                time.sleep(2)
        return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Graph API exception text may contain private provider details.
        message = str(exc) if isinstance(exc, PricesError) else type(exc).__name__
        print(f'ERROR: {message}', file=sys.stderr)
        raise SystemExit(1)
