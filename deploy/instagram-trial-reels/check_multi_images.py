#!/usr/bin/env python3
"""Render a private sample using real source images and licensed illustrations."""
from pathlib import Path
import argparse
import hashlib
import sys
import tempfile
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    sys.path[:0] = [str(runtime), str(runtime/'selector_trial_runtime')]
    import crypto_news_trial as engine
    from instagram_reel_source_image import fetch
    from instagram_reel_commons import collect
    import instagram_trial_reels as reel

    source = 'https://cryptoslate.com/aaves-midnight-usdc-withdrawals-briefly-left-lenders-with-little-spare-cash/'
    story = engine.source_material({'id':'preview', 'source_url':source,
                                    'title_original':'', 'source_name':''}, time.time(),
                                   admin_override=True)
    image_url = story.get('image_url')
    if not image_url:
        raise RuntimeError('The sample article has no lead image.')
    with tempfile.TemporaryDirectory(prefix='kiani-reel-images-') as tmp:
        root = Path(tmp)
        media = []
        seen = set()
        for candidate in [image_url] + [u for u in story.get('image_urls', []) if u != image_url][:4]:
            target = root/('article-' + str(len(media)) + '.jpg')
            try:
                fetch(engine, story['source_url'], candidate, target, timeout=10)
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if digest in seen:
                    target.unlink()
                    continue
                seen.add(digest)
                media.append({'path':target, 'kind':'publisher'})
            except Exception as exc:
                if not media:
                    raise
                print('Optional article image:', type(exc).__name__, flush=True)
                if target.exists():
                    target.unlink()
        print('Verified distinct article images:', len(media), flush=True)
        commons_dir = root/'commons'
        commons_dir.mkdir()
        illustrations = collect({'title_original':'Bitcoin cryptocurrency market update'}, commons_dir, limit=2)
        print('Verified licensed illustrations:', len(illustrations), flush=True)
        if not illustrations:
            raise RuntimeError('No licensed illustration was found for the sample topic.')
        for item in illustrations:
            digest = hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
            if digest not in seen:
                seen.add(digest)
                media.append(item)
        if len(media) < 2:
            raise RuntimeError('The sample did not provide two distinct images.')
        example = {'title_fa':'پیش‌نمایش خبر بازار رمزارز',
                   'summary_fa':('این ویدئو یک نمونه نمایشی برای بررسی تصویر و متن است و منتشر نمی‌شود. '
                                  'در ادامه، نمونه دوم تصویر همراه با متن فارسی نمایش داده می‌شود.'),
                   'source_name':'نمونه محلی', 'story_type':'hard_news'}
        video = root/'preview.mp4'
        duration = reel.render_video(example, 'crypto', video,
            Path.home()/'kiani-instagram-publisher', media=media[:8])
        print('Private sample rendered:', round(duration, 2), 'seconds,', len(media[:8]), 'images', flush=True)
    print('Preflight passed. No DeepSeek or Instagram request was made.', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Multi-image preflight stopped:', type(exc).__name__, str(exc)[:180], file=sys.stderr)
        raise SystemExit(1)

