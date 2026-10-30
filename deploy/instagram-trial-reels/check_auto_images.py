#!/usr/bin/env python3
"""Read-only check of previously failed automatic Reel publisher images."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import sqlite3
import sys
import tempfile
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    runtime = parser.parse_args().runtime.resolve()
    sys.path[:0] = [str(runtime), str(runtime/'selector_trial_runtime')]
    import crypto_news_trial as engine
    import instagram_ranked_news as ranked
    from instagram_reel_source_image import fetch
    db = Path.home()/'.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
    if not db.is_file():
        raise RuntimeError('Reel database unavailable.')
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""SELECT origin, kind, source_url, title_original FROM trial_reels
            WHERE origin IN ('daily_top_story','daily_direct') AND status='failed'
            ORDER BY created_at DESC LIMIT 4""").fetchall()
    if not rows:
        raise RuntimeError('No failed automatic Reel was available for testing.')
    successes = 0
    with tempfile.TemporaryDirectory(prefix='kiani-auto-image-') as tmp:
        for index, row in enumerate(rows, 1):
            try:
                ranked.configure_engine(row['kind'])
                story = engine.source_material({'source_url':row['source_url'],
                    'title_original':row['title_original'] or '', 'source_name':''},
                    time.time(), admin_override=True)
                image = story.get('image_url')
                if not image:
                    raise ValueError('Article has no lead image.')
                dst = Path(tmp)/('sample-'+str(index)+'.jpg')
                fetch(engine, story['source_url'], image, dst, timeout=15)
                successes += 1
                print('Image verified:', urlsplit(story['source_url']).hostname,
                      '| image host:', urlsplit(image).hostname, '| bytes:', dst.stat().st_size, flush=True)
            except Exception as exc:
                print('Image unavailable:', urlsplit(row['source_url']).hostname,
                      '| type:', type(exc).__name__, '| detail:', str(exc)[:160], flush=True)
    print('Verified images:', successes, 'of', len(rows), flush=True)
    if not successes:
        raise RuntimeError('No previously failed article image could be verified.')
    print('Preflight passed. No DeepSeek or Instagram request was made.', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Automatic image preflight stopped:', type(exc).__name__, str(exc)[:180], file=sys.stderr)
        raise SystemExit(1)
