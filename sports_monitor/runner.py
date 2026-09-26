import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from .model import qualifies
from .network import Client, FetchError
from .parsing import discover, parse_product, ParseError
from .state import State
from .stores import STORES
from .telegram import batches, send, DeliveryError

AKINON = {'barcin', 'sporjinal', 'superstep', 'sportive'}


def fetch_url(store, url):
    if store.key not in AKINON:
        return url
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    params['format'] = 'json'
    return urlunsplit(parts._replace(query=urlencode(params)))


@contextmanager
def lock(path):
    """OS lock releases on crash; the persistent file itself is not a lock."""
    with open(path, 'a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def scan_store(store, known, max_pages, max_products):
    client = Client(store.root)
    pending = [store.root + p for p in store.listings]
    seen, urls, products = set(), set(known), {}
    report = {'store': store.key, 'listing_pages': 0, 'discovered': 0, 'parsed': 0, 'errors': [], 'limited': False}
    try:
        while pending and len(seen) < max_pages:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            final, html = client.get(fetch_url(store, url))
            found, more = discover(store.key, final, html)
            urls.update(found)
            pending.extend(u for u in more if u not in seen)
        report['listing_pages'] = len(seen)
        report['discovered'] = len(urls)
        report['limited'] = bool(pending) or len(urls) > max_products
        if not urls:
            report['errors'].append({'stage': 'discovery', 'error': 'No product links; catalog schema or access requires attention'})
        for url in sorted(urls)[:max_products]:
            try:
                final, html = client.get(fetch_url(store, url))
                product = parse_product(store.key, final, html, int(time.time()))
                products[product.key] = product
            except (FetchError, ParseError, ValueError, KeyError, TypeError, AttributeError) as exc:
                # Limit log volume, but retain the full error count.
                report['product_errors'] = report.get('product_errors', 0) + 1
                if len(report['errors']) < 10:
                    report['errors'].append({'url': url, 'error': str(exc)[:180]})
        report['parsed'] = len(products)
    except (FetchError, ValueError, KeyError, TypeError) as exc:
        report['errors'].append({'stage': 'listing', 'error': str(exc)[:180]})
    finally:
        client.session.close()
    return list(products.values()), report


def run(args):
    now = int(time.time())
    destination = os.environ.get('RUN_DISCOUNT_CHAT_ID', '@alanchandetest')
    token = os.environ.get('RUN_DISCOUNT_BOT_TOKEN')
    if args.publish and (not token or not os.environ.get('RUN_DISCOUNT_CHAT_ID')):
        raise ValueError('Publishing requires RUN_DISCOUNT_BOT_TOKEN and RUN_DISCOUNT_CHAT_ID')
    state = State(':memory:' if not args.publish else args.db)
    if not args.publish and Path(args.db).exists():
        with sqlite3.connect(f'file:{Path(args.db).resolve().as_posix()}?mode=ro', uri=True) as source:
            source.backup(state.db)
    selected = [s for s in STORES if not args.stores or s.key in args.stores]
    report = {'started_at': now, 'publish': args.publish, 'stores': [], 'messages': [], 'recheck_errors': []}
    try:
        futures = {}
        observed = []
        with ThreadPoolExecutor(max_workers=min(8, len(selected))) as pool:
            for store in selected:
                futures[pool.submit(scan_store, store, state.known_urls(store.key), args.max_pages, args.max_products)] = store
            for future in as_completed(futures):
                products, result = future.result()
                report['stores'].append(result)
                observed.extend(products)
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
        # Determine eligibility before inserting the current scan into history.
        candidates = [(p, state.reason(p, destination, int(time.time()))) for p in observed]
        for p in observed:
            state.observe(p)
        candidates = [(p, reason) for p, reason in candidates if reason]
        candidates.sort(key=lambda pair: (pair[0].discount, pair[0].original - pair[0].sale, len(pair[0].sizes)), reverse=True)
        fresh = []
        # Re-read finalists just before publishing; earlier observations may be hours old.
        for p, reason in candidates:
            if len(fresh) >= args.top:
                break
            store = next(s for s in selected if s.key == p.store)
            client = Client(store.root)
            try:
                final, html = client.get(fetch_url(store, p.url))
                current = parse_product(store.key, final, html, int(time.time()))
                if current.key != p.key:
                    raise ParseError('Product identity changed on recheck')
                if current.fingerprint != p.fingerprint:
                    # A changed finalist waits until the next scan for fresh ranking.
                    state.observe(current)
                    continue
                fresh.append((current, reason))
            except (FetchError, ValueError, KeyError, TypeError, AttributeError) as exc:
                report['recheck_errors'].append({'url': p.url, 'error': str(exc)[:180]})
            finally:
                client.session.close()
        report['eligible'] = len(candidates)
        report['selected'] = len(fresh)
        for text, products in batches(fresh, args.group_size):
            if any(int(time.time()) - p.observed_at > 300 for p in products):
                report['recheck_errors'].append({'error': 'Finalists exceeded five-minute freshness limit'})
                continue
            if not args.publish:
                print(text + '\n')
                continue
            batch = state.reserve(destination, text, products)
            try:
                message_id = send(token, destination, text)
            except DeliveryError as exc:
                state.failed(batch, exc.ambiguous)
                report['messages'].append({'outbox_id': batch, 'error': str(exc), 'ambiguous': exc.ambiguous})
                break
            state.delivered(batch, message_id, int(time.time()))
            report['messages'].append({'outbox_id': batch, 'message_id': message_id, 'destination': destination})
        report['finished_at'] = int(time.time())
        report['degraded'] = bool(report['recheck_errors']) or any(s['errors'] or s['limited'] for s in report['stores']) or any('error' in m for m in report['messages'])
        if args.publish:
            with state.db:
                state.db.execute('INSERT INTO scans(started_at,finished_at,report) VALUES(?,?,?)', (now, report['finished_at'], json.dumps(report)))
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return 2 if report['degraded'] else 0
    finally:
        state.close()


def main():
    parser = argparse.ArgumentParser(description='Scan Turkish sports deals. Default: dry run; never posts or changes history.')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--db', default=os.environ.get('RUN_DISCOUNT_DB', 'var/sports-monitor.sqlite3'))
    parser.add_argument('--report', default='var/latest-scan.json')
    parser.add_argument('--stores', nargs='+', choices=[s.key for s in STORES])
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--max-products', type=int, default=5000)
    parser.add_argument('--top', type=int, choices=range(5, 11), default=10)
    parser.add_argument('--group-size', type=int, choices=range(5, 11), default=7)
    parser.add_argument('--resolve-batch', type=int)
    parser.add_argument('--message-id', type=int)
    parser.add_argument('--confirmed-not-sent', action='store_true')
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_products < 1:
        parser.error('Scan limits must be positive')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock(args.db + '.lock'):
            if args.resolve_batch:
                if bool(args.message_id) == args.confirmed_not_sent:
                    parser.error('Reconcile using either --message-id or --confirmed-not-sent')
                state = State(args.db)
                try:
                    state.resolve(args.resolve_batch, args.message_id)
                finally:
                    state.close()
                return 0
            return run(args)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'Monitor stopped: {exc}', file=sys.stderr)
        return 1
