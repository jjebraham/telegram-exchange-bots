#!/usr/bin/env python3
"""Privately render long and short Reels without model or Instagram calls."""
import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True, type=Path)
p.add_argument('--assets', type=Path, default=Path.home()/'kiani-instagram-publisher')
p.add_argument('--cached-url')
args = p.parse_args()
root = args.runtime.resolve()
sys.path[:0] = [str(root), str(root/'selector_trial_runtime')]
import instagram_manual_news_intake as intake
import instagram_trial_reels as reel
import economy_news_translation as translation
from PIL import Image

material = dict(title_original='News about financial markets', source_text='Sample source text',
                source_name='Example', article_date='', source_url='https://example.com/news')
title = 'نمونه خبری درباره بازار و فناوری'
summary = ' '.join('این جمله نمونه درباره بازار و خبرهای اقتصادی است.' for _ in range(12))
if args.cached_url:
    import crypto_news_trial as engine
    import instagram_ranked_news as ranked
    from economy_news_translation import load_translation_env
    load_translation_env(Path.home()/'sub/.env')
    ranked.configure_engine('crypto')
    intake.configure_admin_source(engine, args.cached_url)
    material = intake.read_manual_source(engine, dict(id='reel-check', source_url=args.cached_url,
        title_original='', source_name=''), time.time(), relaxed=True)
    source = material['title_original']+'\n'+material['source_text']+'\n'+material['article_date']
    prefix = 'coindesk-rss-v1-json\n' if material.get('source_scope') == 'coindesk_rss_summary' else 'economy-v2-json\n'
    key = hashlib.sha256((prefix+os.getenv('DEEPSEEK_MODEL','deepseek-flash')+'\n'+source).encode()).hexdigest()
    db = Path.home()/'.local/state/kiani-instagram-manual-news/assessment.sqlite3'
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as con:
        cached = con.execute('SELECT title_fa,summary_fa FROM economy_translation_cache WHERE input_hash=?',(key,)).fetchone()
    if not cached:
        raise RuntimeError('No matching saved translation; no model call was made.')
    title, summary = cached

chunks = reel._chunks(summary)
if not chunks or len(chunks) > 16 or ' '.join(chunks).split() != summary.split():
    raise RuntimeError('Long Reel did not preserve all summary words.')
print('Long summary: complete;', len(chunks), 'text cards.', flush=True)

# Exercise the validation-failure fallback without calling the model.
old_request, old_key = translation.request_completion, os.environ.get('DEEPSEEK_API_KEY')
translation.request_completion = lambda body, key: translation.Completion('{invalid json')
os.environ['DEEPSEEK_API_KEY'] = 'offline-test-key'
try:
    short = intake.short_reel_summary(title, summary, material)
finally:
    translation.request_completion = old_request
    if old_key is None: os.environ.pop('DEEPSEEK_API_KEY', None)
    else: os.environ['DEEPSEEK_API_KEY'] = old_key
if not short or short not in summary:
    raise RuntimeError('Short fallback did not use complete original summary text.')
print('Short fallback: complete sentences from saved summary.', flush=True)

with tempfile.TemporaryDirectory(prefix='kiani-long-reel-check-') as tmp:
    directory = Path(tmp)
    reel.STATE = directory
    picture1, picture2 = directory/'cover.jpg', directory/'body.jpg'
    Image.new('RGB',(900,500),'#235172').save(picture1)
    Image.new('RGB',(900,500),'#a76b37').save(picture2)
    media = [{'path':picture1,'kind':'publisher'}, {'path':picture2,'kind':'publisher'}]
    for length, text in (('long',summary),('short',short)):
        story = dict(title_fa=title, summary_fa=text, source_name=material['source_name'],
                     story_type='hard_news', reel_length=length)
        duration = reel.render_video(story, 'crypto', directory/(length+'.mp4'), args.assets, media=media)
        if (length == 'long' and not 12 <= duration <= 90.15 or
                length == 'short' and not 14.85 <= duration <= 30.15):
            raise RuntimeError('Reel duration differs from the selected mode.')
        print('Private', length, 'Reel verified:', round(duration,2), 'seconds.', flush=True)
print('No DeepSeek, Telegram or Instagram request was made.')

