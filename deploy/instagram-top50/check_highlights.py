#!/usr/bin/env python3
"""Check four-image carousel compatibility without publishing anything."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    import instagram_top50_prices as app
    from crypto_top50_data import validate_snapshot
    account = os.environ.get('INSTAGRAM_USER_ID', '').strip()
    if not account.isdigit() or not os.environ.get('INSTAGRAM_ACCESS_TOKEN', '').strip():
        raise RuntimeError('Existing Instagram environment is not loaded.')
    assets = Path.home() / 'kiani-instagram-publisher'
    runtime_hash = app.fingerprint(runtime, app.RUNTIME_FILES)
    assets_hash = app.fingerprint(assets, app.SHARED_FILES)
    preview_dir = Path('/var/www/peerexo.com/public/instagram-rates/top50-gainers-preview')
    public_base = 'https://peerexo.com/instagram-rates/top50-gainers-preview/'
    with sqlite3.connect(app.DEFAULT_DB.resolve().as_uri() + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        chosen = None
        for row in con.execute('SELECT * FROM top50_snapshots WHERE created_at BETWEEN ? AND ? ORDER BY created_at DESC',
                               (time.time()-24*3600, time.time())):
            manifest = json.loads(row['manifest_json'])
            if (manifest.get('top50_runtime_fingerprint') == runtime_hash and
                manifest.get('shared_assets_fingerprint') == assets_hash and not manifest.get('sample') and
                manifest.get('sections') == list(app.SECTIONS) and
                len(manifest.get('images', [])) == 4):
                validate_snapshot(json.loads(row['data_json']))
                chosen = (row['id'], manifest)
                break
    if chosen is None:
        raise RuntimeError('A matching four-slide source preview is required first.')
    preview_id, manifest = chosen
    paths = [Path(p) for p in manifest['images']]
    if len(set(paths)) != 4 or any(p.parent != preview_dir or p.suffix.lower() != '.jpg' or not p.is_file() for p in paths):
        raise RuntimeError('Preview paths are invalid.')
    urls = [public_base + quote(p.name) for p in paths]
    spec = importlib.util.spec_from_file_location('highlights_publisher', assets / 'instagram_daily_rates.py')
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(helper.verify_public_image, urls))
    def create_child(url):
        child = helper._create_container({'image_url': url, 'is_carousel_item': 'true'})
        helper._wait_for_container(child)
        return child
    print('Checking four Meta image containers; nothing will be published.', flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        children = list(pool.map(create_child, urls))
    parent = helper._create_container({'media_type': 'CAROUSEL', 'children': ','.join(children),
                                       'caption': 'Private unpublished carousel compatibility check.'})
    helper._wait_for_container(parent)
    receipt = dict(revision=args.revision, runtime_hash=runtime_hash, assets_hash=assets_hash, preview_id=preview_id,
                   account_hash=hashlib.sha256(account.encode()).hexdigest(),
                   token_hash=hashlib.sha256(os.environ['INSTAGRAM_ACCESS_TOKEN'].strip().encode()).hexdigest(),
                   checked_at=time.time(), ready=True)
    directory = app.DEFAULT_DB.parent
    fd, name = tempfile.mkstemp(prefix='.meta4-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(receipt, out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o600)
        os.replace(name, directory / 'meta-4-carousel-proof.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('Meta accepted four image containers and a ready carousel container; nothing published.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Meta compatibility check stopped:', type(exc).__name__, file=sys.stderr)
        print('No carousel was published and the existing schedule is unchanged.', file=sys.stderr)
        raise SystemExit(1)
