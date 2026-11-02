#!/usr/bin/env python3
"""Check image collection on one public article; never publish or use a model."""
import argparse
from pathlib import Path
import sys
import tempfile
import time

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True, type=Path)
p.add_argument('--url', required=True)
p.add_argument('--mode', choices=('manual','automatic'), default='manual')
args = p.parse_args()
root = args.runtime.resolve()
sys.path[:0] = [str(root), str(root/'selector_trial_runtime')]
import crypto_news_trial as engine
import instagram_ranked_news as ranked
import instagram_manual_news_intake as intake
from instagram_news_slide_images import collect, caption_credit, image_key
from instagram_reel_stock import queries

ranked.configure_engine('crypto')
intake.configure_admin_source(engine, args.url)
material = intake.read_manual_source(engine, dict(id='image-check', source_url=args.url,
    title_original='', source_name=''), time.time(), relaxed=True)
print('Article image candidates:', len(material.get('image_urls') or []))
print('Stock search topics:', queries(material))
with tempfile.TemporaryDirectory(prefix='kiani-news-images-check-') as tmp:
    images = collect(engine, material, Path(tmp), origin=args.mode, minimum=2)
    if image_key(images[0]['path']) == image_key(images[1]['path']):
        raise RuntimeError('First two images are not distinct.')
    print('Verified distinct images:', len(images))
    print('Cover source:', images[0].get('provider') or images[0].get('kind'))
    print('Second slide source:', images[1].get('provider') or images[1].get('kind'))
    print('Illustration credits prepared:', bool(caption_credit(images)))
print('Image search may update its private provider cache; no model or Instagram request was made.')

