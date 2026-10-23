#!/usr/bin/env python3
"""Daily 10:00 Tehran gold board; skip unless all current prices pass checks."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, time as wall_time, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

from iran_gold_data import GoldError, TEHRAN, UTC, SPEC, collect, percent, stamp, validate
from instagram_iran_gold_renderer import ICON_FILES, TEMPLATE_VERSION, caption, render
from instagram_economic_calendar_renderer import labels

STATE = Path.home() / '.local/state/kiani-instagram-iran-gold'
PUBLIC = Path('/var/www/peerexo.com/public/instagram-rates')
BASE = 'https://peerexo.com/instagram-rates'
FILES = ('iran_gold_data.py', 'iran_gold_quorum.py', 'iran_gold_servix.py', 'instagram_iran_gold.py', 'instagram_iran_gold_renderer.py',
         'economic_calendar_data.py', 'instagram_economic_calendar_renderer.py', 'tests/test_instagram_iran_gold.py',
         'tests/test_iran_gold_servix.py', 'tests/test_iran_gold_template.py',
         'deploy/instagram-iran-gold/activate_servix.py',
         'deploy/instagram-iran-gold/activate_template.py') + ICON_FILES
ASSETS = ('assets/instagram/kiani-logo.svg', 'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')


def fingerprint(root, names=FILES):
    return hashlib.sha256(b'\0'.join(name.encode() + b'\0' + (Path(root) / name).read_bytes() for name in names)).hexdigest()


def next_run(now):
    local = now.astimezone(TEHRAN)
    start = local.replace(hour=10, minute=0, second=0, microsecond=0)
    return start if start > local else start + timedelta(days=1)


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GoldError('Another gold publisher is active.') from None
        yield


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    con = sqlite3.connect(path, timeout=15)
    os.chmod(path, 0o600)
    con.row_factory = sqlite3.Row
    con.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS gold_previews (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, runtime_hash TEXT NOT NULL,
            assets_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, manifest_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gold_history (
            day TEXT PRIMARY KEY, observed_at TEXT NOT NULL, prices_json TEXT NOT NULL, media_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS instagram_news_publications (
            day TEXT PRIMARY KEY, status TEXT NOT NULL, started_at REAL NOT NULL,
            finished_at REAL, container_id TEXT, media_id TEXT, manifest_json TEXT NOT NULL, error_type TEXT);
    ''')
    return con


def last_prices(con):
    row = con.execute('SELECT prices_json FROM gold_history ORDER BY day DESC LIMIT 1').fetchone()
    return json.loads(row[0]) if row else None


def comparison(con, now, hours):
    eligible = []
    for row in con.execute('SELECT * FROM gold_history ORDER BY day DESC LIMIT 45'):
        observed = stamp(row['observed_at'])
        age = (now.astimezone(UTC) - observed).total_seconds() / 3600
        if abs(age - hours) <= (1 if hours == 24 else 3):
            prices = json.loads(row['prices_json'])
            if set(prices) == set(SPEC):
                eligible.append((abs(age - hours), row['day'], prices))
    return min(eligible, key=lambda x: (x[0], x[1]))[2] if eligible else {}


def add_changes(con, snapshot):
    generated = stamp(snapshot['generated_at'])
    daily, monthly = comparison(con, generated, 24), comparison(con, generated, 720)
    for row in snapshot['rows']:
        row['day'] = percent(row['price'], daily.get(row['id']))
        row['month'] = percent(row['price'], monthly.get(row['id']))


def check_changes(con, snapshot):
    expected = json.loads(json.dumps(snapshot))
    add_changes(con, expected)
    if any(a[k] != b[k] for a, b in zip(snapshot['rows'], expected['rows']) for k in ('day', 'month')):
        raise GoldError('Displayed changes do not match verified publication history.')


def already(con, day):
    row = con.execute('SELECT status,media_id FROM instagram_news_publications WHERE day=?', (day,)).fetchone()
    if row and row['status'] == 'published':
        print('Already published gold board for this Tehran day:', row['media_id'])
        return True
    if row and row['status'] in {'preparing', 'publishing', 'needs_review'}:
        raise GoldError('Earlier gold publication requires review; no automatic duplicate.')
    return False


def publication_key(con, day, template_test=False):
    if not template_test:
        return day
    original = con.execute('SELECT status FROM instagram_news_publications WHERE day=?', (day,)).fetchone()
    if original and original['status'] in {'preparing', 'publishing', 'needs_review'}:
        raise GoldError('Earlier daily gold publication requires review before a template test.')
    # A separately authorized design test must not overwrite the daily row or
    # comparison history. Its stable key also blocks a second test on rerun.
    return day + ':' + TEMPLATE_VERSION


def helper(root):
    spec = importlib.util.spec_from_file_location('kiani_iran_gold_graph', root / 'instagram_daily_rates.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def publish(con, snapshot, manifest, assets, *, authorized_day=None, template_test=False):
    if snapshot.get('status') != 'verified':
        raise GoldError('Blocked gold board cannot reach Instagram.')
    if template_test and (not authorized_day or manifest.get('template_version') != TEMPLATE_VERSION):
        raise GoldError('A template test requires an explicit day and the reviewed template version.')
    validate(snapshot, publishing=True, baseline=last_prices(con), authorized_day=authorized_day)
    check_changes(con, snapshot)
    day = stamp(snapshot['generated_at']).astimezone(TEHRAN).date().isoformat()
    key = publication_key(con, day, template_test)
    if already(con, key):
        return
    if not os.getenv('INSTAGRAM_USER_ID') or not os.getenv('INSTAGRAM_ACCESS_TOKEN'):
        raise GoldError('Existing private Instagram configuration is not loaded.')
    graph = helper(assets)
    if len(manifest['image_urls']) != 1:
        raise GoldError('Expected exactly one gold price board.')
    graph.verify_public_image(manifest['image_urls'][0])
    with con:
        con.execute('''INSERT INTO instagram_news_publications(day,status,started_at,manifest_json)
            VALUES (?,'preparing',?,?) ON CONFLICT(day) DO UPDATE SET status='preparing',
            started_at=excluded.started_at,finished_at=NULL,container_id=NULL,media_id=NULL,
            manifest_json=excluded.manifest_json,error_type=NULL''', (key, time.time(), json.dumps(manifest, ensure_ascii=False)))
    final_started = False
    try:
        parent = graph._create_container({'image_url': manifest['image_urls'][0], 'caption': manifest['caption']})
        if not re.fullmatch(r'\d+', str(parent)):
            raise GoldError('Invalid Instagram container ID.')
        with con:
            con.execute('UPDATE instagram_news_publications SET container_id=? WHERE day=?', (parent, key))
        graph._wait_for_container(parent)
        # Verify again after rendering, URL retrieval and Meta preparation. Nothing
        # can turn a now-stale board into a post by reusing the collection timestamp.
        validate(snapshot, publishing=True, baseline=last_prices(con), authorized_day=authorized_day)
        check_changes(con, snapshot)
        with con:
            con.execute("UPDATE instagram_news_publications SET status='publishing' WHERE day=?", (key,))
        final_started = True
        media = graph._publish_container(parent)
        if not re.fullmatch(r'\d+', str(media)):
            raise GoldError('Invalid Instagram media ID.')
        with con:
            con.execute("UPDATE instagram_news_publications SET status='published',media_id=?,finished_at=? WHERE day=?", (media, time.time(), key))
            if not template_test:
                con.execute('INSERT INTO gold_history VALUES (?,?,?,?)',
                            (day, snapshot['generated_at'], json.dumps({r['id']: r['price'] for r in snapshot['rows']}), media))
        print('Published Iran gold ' + ('template test' if template_test else 'board') + ' (media id: ' + str(media) + ').')
    except BaseException as exc:
        with con:
            con.execute('UPDATE instagram_news_publications SET status=?,finished_at=?,error_type=? WHERE day=?',
                        ('needs_review' if final_started else 'failed', time.time(), type(exc).__name__, key))
        raise


def self_check(runtime, assets):
    labels(datetime.now(TEHRAN), assets)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    env['KIANI_GOLD_TEST_ASSETS'] = str(assets)
    libs = str(assets / 'instagram_calendar_libs')
    env['PYTHONPATH'] = libs + os.pathsep + env.get('PYTHONPATH', '')
    subprocess.run([sys.executable, str(runtime / 'tests/test_instagram_iran_gold.py')],
                   check=True, env=env, cwd=runtime, timeout=45)
    subprocess.run([sys.executable, str(runtime / 'tests/test_iran_gold_servix.py')],
                   check=True, env=env, cwd=runtime, timeout=45)
    subprocess.run([sys.executable, str(runtime / 'tests/test_iran_gold_template.py')],
                   check=True, env=env, cwd=runtime, timeout=45)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--publish', action='store_true')
    actions.add_argument('--publish-now-on', metavar='YYYY-MM-DD')
    actions.add_argument('--template-test-on', metavar='YYYY-MM-DD')
    parser.add_argument('--require-servix', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--asset-root', type=Path, default=Path.home() / 'kiani-instagram-publisher')
    parser.add_argument('--state', type=Path, default=STATE)
    args = parser.parse_args()
    os.umask(0o077)
    labels(datetime.now(TEHRAN), args.asset_root)  # Load the pinned Persian calendar library before source date checks.
    if args.self_check:
        self_check(Path(__file__).parent, args.asset_root)
        return 0
    now = datetime.now(TEHRAN)
    authorized_day = args.template_test_on or args.publish_now_on
    publishing = bool(args.publish or authorized_day)
    if authorized_day and authorized_day != now.date().isoformat():
        raise GoldError('One-time publication date must be the current Tehran day.')
    if args.publish and not wall_time(10) <= now.time() < wall_time(10, 15):
        raise GoldError('Gold publication is allowed only 10:00–10:15 Tehran.')
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(args.state / ('publication.lock' if publishing else 'preview.lock')):
        con = database(args.state / 'gold.sqlite3')
        try:
            if args.status:
                for row in con.execute('SELECT day,status,media_id,finished_at,error_type FROM instagram_news_publications ORDER BY day DESC LIMIT 8'):
                    print(json.dumps(dict(row)))
                return 0
            key = publication_key(con, now.date().isoformat(), bool(args.template_test_on))
            if publishing and already(con, key):
                return 0
            folder = args.state / 'runs' / (now.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
            folder.mkdir(parents=True, mode=0o700)
            snapshot = collect(last_prices(con))
            manifest = {}
            if snapshot['status'] == 'verified':
                validate(snapshot, baseline=last_prices(con))
                add_changes(con, snapshot)
                segment = 'iran-gold' if publishing else 'iran-gold-preview'
                output = PUBLIC / segment
                output.mkdir(parents=True, exist_ok=True, mode=0o755); output.chmod(0o755)
                images = render(snapshot, output, args.asset_root, preview=not publishing)
                text = caption(snapshot, args.asset_root)
                if len(text) > 2200:
                    raise GoldError('Gold caption exceeds Instagram capacity.')
                manifest = dict(kind='iran_gold', images=images,
                    image_urls=[BASE + '/' + segment + '/' + Path(p).name for p in images],
                    caption=text, generated_at=snapshot['generated_at'], timezone='Asia/Tehran',
                    publication_mode='owner_requested_template_test' if args.template_test_on else 'owner_requested_once' if args.publish_now_on else 'scheduled' if publishing else 'preview',
                    authorized_day=authorized_day, template_version=TEMPLATE_VERSION)
                for url in manifest['image_urls']:
                    print('Gold slide:', url, flush=True)
            report = dict(snapshot=snapshot, manifest=manifest)
            (folder / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Gold source checks:', json.dumps(snapshot['health'], ensure_ascii=False), flush=True)
            if args.require_servix:
                contributions = [r for r in snapshot.get('rows', []) if 'servix' in r.get('sources', [])]
                if len(contributions) < 2:
                    print('Private audit:', folder / 'audit.json', flush=True)
                    raise GoldError('Live Servix corroboration of at least two prices is required for this upgrade/post.')
            if snapshot.get('schema_version') == 2 and snapshot['status'] == 'verified':
                print('Gold consensus:', json.dumps({row['id']: dict(sources=row['sources'],
                    selected=row['selected_source'], price=row['price'], agreement_pct=row['agreement_pct'],
                    excluded=row['rejected_sources']) for row in snapshot['rows']}, ensure_ascii=False), flush=True)
            if not publishing:
                with con:
                    con.execute('INSERT INTO gold_previews VALUES (?,?,?,?,?,?)',
                        (folder.name, time.time(), fingerprint(Path(__file__).parent), fingerprint(args.asset_root, ASSETS),
                         json.dumps(snapshot, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False)))
            if snapshot['status'] != 'verified':
                print('SKIPPED gold post:', snapshot['reason'], 'Nothing published.', flush=True)
            elif publishing:
                publish(con, snapshot, manifest, args.asset_root, authorized_day=authorized_day,
                        template_test=bool(args.template_test_on))
            else:
                print('Verified preview only. No Instagram API contact or schedule change.')
            print('Private audit:', folder / 'audit.json', flush=True)
            return 0 if snapshot['status'] == 'verified' or snapshot['code'] == 'stale' else 1
        finally:
            con.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR:', str(exc) if isinstance(exc, GoldError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

