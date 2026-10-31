#!/usr/bin/env python3
"""Read-only verification of the selected article and its lead image."""
import argparse
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True)
args = parser.parse_args()
runtime = args.runtime.resolve()
sys.path[:0] = [str(runtime), str(runtime/'selector_trial_runtime')]
import crypto_news_trial as engine
import instagram_ranked_news as ranked
import instagram_manual_news_intake as intake
from instagram_reel_source_image import fetch

url = 'https://blockchain.news/news/20261031-price-prediction-algo-14-oi-surge-cant-crack-010'
try:
    ranked.configure_engine('crypto')
    intake.configure_admin_source(engine, url)
    material = intake.read_manual_source(engine, {
        'id': 'admin-source-check', 'source_url': url,
        'title_original': '', 'source_name': ''}, time.time(), relaxed=True)
    print('Article host:', urlsplit(material['source_url']).hostname, flush=True)
    print('Publisher:', material['source_name'], flush=True)
    print('Headline characters:', len(material.get('title_original', '')), flush=True)
    print('Source text characters:', len(material.get('source_text', '')), flush=True)
    print('Publication time evidence:', material.get('date_evidence'), flush=True)
    image_url = material.get('image_url')
    print('Lead image host:', urlsplit(image_url).hostname if image_url else 'missing', flush=True)
    with tempfile.TemporaryDirectory(prefix='kiani-source-check-') as tmp:
        path = fetch(engine, material['source_url'], image_url, Path(tmp)/'lead.jpg', timeout=20)
        print('Lead image verified:', path.stat().st_size, 'bytes', flush=True)
    print('Source preflight passed; no DeepSeek, Telegram or Instagram request was made.')
except Exception as exc:
    print('Source preflight stopped:', type(exc).__name__, 'HTTP:', getattr(exc, 'code', None),
          'detail:', str(exc)[:240], flush=True)
    raise SystemExit(1)
