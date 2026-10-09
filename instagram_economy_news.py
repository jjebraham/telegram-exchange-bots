#!/usr/bin/env python3
"""Collect economy news and preview or publish the highest-ranked eligible report."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from economy_news_picker import collect, init_storage, rank, source_weight
from economy_news_translation import article_material, load_translation_env, translate
from instagram_crypto_news import NewsError, database, publish, save_story

DEFAULT_DB = Path.home() / '.local/state/kiani-instagram-economy/economy.sqlite3'
DEFAULT_OUTPUT = Path('/var/www/peerexo.com/public/instagram-rates/economy')
DEFAULT_BASE = 'https://peerexo.com/instagram-rates/economy'
RUNTIME_FILES = ('instagram_economy_news.py', 'economy_news_picker.py',
                 'economy_news_translation.py', 'instagram_news_renderer.py', 'instagram_crypto_news.py')


def runtime_fingerprint(root=None):
    root = Path(root or Path(__file__).resolve().parent)
    return hashlib.sha256(b'\0'.join((name.encode() + b'\0' + (root / name).read_bytes())
                                   for name in RUNTIME_FILES)).hexdigest()


@contextmanager
def run_lock(db):
    path = Path(str(db) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if os.name != 'nt':
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NewsError('Another economy news run is active; skipped.') from None
        else:
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise NewsError('Another economy news run is active; skipped.') from None
        yield


def prepare(con, story, output):
    from instagram_news_renderer import hero_image
    errors = []
    # Bound the work per group and prefer original publisher links over Google hops.
    from urllib.parse import urlsplit
    ordered = sorted(story.items, key=lambda i: (
        urlsplit(i.link).hostname != 'news.google.com', source_weight(i.source), i.published), reverse=True)
    seen_sources, sources = set(), []
    for item in ordered:
        if item.source.lower() not in seen_sources:
            sources.append(item)
            seen_sources.add(item.source.lower())
    for item in sources[:4]:
        try:
            material = article_material(item)
            if hero_image(material, output / '.source-images') is None:
                raise NewsError('Source illustration could not be downloaded.')
            # Errors here must abort rather than quietly switching stories on API failure.
        except NewsError as exc:
            errors.append(str(exc))
            continue
        title, summary = translate(con, material)
        saved = dict(material, title_fa=title, summary_fa=summary, origin='manual')
        key = save_story(con, saved)
        with con:
            con.execute('''INSERT OR REPLACE INTO economy_preparations VALUES (?,?,?,?,?,?)''',
                        (key, json.dumps([i.title for i in story.items]),
                         json.dumps([i.id for i in story.items]), material['source_text'],
                         material['source_url'], time.time()))
        saved = dict(con.execute('SELECT * FROM instagram_news WHERE id=?', (key,)).fetchone())
        return saved, material, item
    raise NewsError('No usable article with a source picture in this group: ' + '; '.join(sorted(set(errors))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--public-base', default=DEFAULT_BASE)
    parser.add_argument('--publisher-root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--translation-env', type=Path)
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--no-fetch', action='store_true')
    parser.add_argument('--candidates', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.publish and any((args.dry_run, args.collect_only, args.candidates, args.status)):
        parser.error('--publish cannot be combined with collection/preview/status actions')
    db = args.db.expanduser().resolve()
    with run_lock(db), database(db) as con:
        init_storage(con)
        if args.status:
            for row in con.execute('''SELECT n.title_fa,n.source_url,p.status,p.media_id
                FROM instagram_news n LEFT JOIN instagram_news_publications p ON n.id=p.story_id
                ORDER BY n.imported_at DESC LIMIT 10'''):
                print(json.dumps(dict(row), ensure_ascii=False))
            return 0
        if not args.no_fetch:
            print('Economy collection:', json.dumps(collect(con)))
        if args.collect_only:
            return 0
        stories = rank(con)
        for index, story in enumerate(stories[:10], 1):
            print(f'{index}. score={story.score} outlets={len(story.sources)}: {story.lead.title}')
            print('   Ranking:', json.dumps(story.breakdown))
        if args.candidates:
            return 0
        if not stories:
            raise NewsError('No eligible unpublished economy story from the last 24 hours.')
        load_translation_env(args.translation_env)
        # Accessibility is checked before paying to translate. Try other sources in
        # the same group first, then report the reason for trying the next group.
        chosen = None
        for story in stories[:10]:
            try:
                saved, material, lead = prepare(con, story, args.output)
            except NewsError as exc:
                if str(exc).startswith('No usable article with a source picture'):
                    print('Candidate omitted:', story.lead.title, '|', str(exc))
                    continue
                raise
            chosen = story
            break
        if chosen is None:
            raise NewsError('The top ten groups had no usable source article and picture; no post created.')
        from instagram_news_renderer import render_news
        paths, caption, manifest = render_news([saved], args.output, args.publisher_root,
            news_label='خبر اقتصادی', caption_title='صرافی کیانی | خبر اقتصادی',
            caption_footer='خبر اقتصادی روز | kiani.exchange', require_image=True)
        manifest['economy_ranking'] = dict(score=chosen.score, breakdown=chosen.breakdown,
            sources=sorted(chosen.sources), titles=[i.title for i in chosen.items])
        manifest['economy_runtime_fingerprint'] = runtime_fingerprint()
        print('Selected economy story:', saved['title_fa'])
        for path in paths:
            print('Economy slide:', path)
        print(caption)
        if not args.publish:
            print('Preview complete; Instagram was not contacted.')
            return 0
        now = time.time()
        if not now - 86400 <= lead.published <= now:
            raise NewsError('The selected article expired from the 24-hour window during preparation.')
        sys.path.insert(0, str(args.publisher_root.resolve()))
        import instagram_daily_rates as ig
        os.environ['INSTAGRAM_PUBLIC_MEDIA_BASE_URL'] = args.public_base
        media_id = publish(con, [saved], paths, caption, ig, manifest)
        print(f'Published Instagram economy news ({len(paths)} slides, media id: {media_id})')
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
