#!/usr/bin/env python3
"""Privately verify readable manual news layout, optionally with a saved translation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import types

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True, type=Path)
p.add_argument('--assets', type=Path, default=Path.home()/'kiani-instagram-publisher')
p.add_argument('--cached-url')
args = p.parse_args()
root = args.runtime.resolve()
sys.path[:0] = [str(root), str(root/'selector_trial_runtime')]
import instagram_manual_news_intake as intake
import instagram_news_renderer as renderer

renderer.hero_image = lambda story, cache: None
assets = args.assets

def check(material, title, summary, output):
    fake = types.SimpleNamespace(translate=lambda con, row: (title, summary))
    _, paths, _, manifest = intake.prepare_admin_news(None, material, 'crypto', output, assets, fake)
    if manifest.get('body_font_px') != 64 or not manifest.get('text_complete'):
        raise RuntimeError('Full readable text was not preserved.')
    if manifest.get('summary_normalized') != re.sub(r'\s+', ' ', summary).strip():
        raise RuntimeError('Summary changed during rendering.')
    if len(paths) < 2 or len(paths) > 10 or not all(p.is_file() for p in paths):
        raise RuntimeError('Unexpected manual carousel pages.')
    return len(paths)

with tempfile.TemporaryDirectory(prefix='kiani-admin-layout-') as tmp:
    output = Path(tmp)
    fixture = dict(source_url='https://example.com/news', source_name='Example', image_url=None,
                   article_date='', title_original='Crypto price prediction',
                   assessment={'story_type':'forecast'}, article_published_at=0)
    text = ('تحلیل‌گران درباره وضعیت بازار و تغییر روند قیمت هشدار دادند. '
            'ارزش دارایی با توجه به داده‌های معاملاتی می‌تواند در محدوده متفاوتی قرار گیرد. '
            'سرمایه‌گذاران باید شرایط، ریسک و عدم قطعیت این پیش‌بینی را در نظر بگیرند. '
            'ترکیب BTC و Ethereum با اعداد ۱۲۳٬۴۵۶ و ۳٫۵ درصد فقط نمونه آزمایشی است.')
    print('Offline Persian text layout:', check(fixture, 'بررسی پیش‌بینی بازار رمزارزها', text, output), 'slides; 64px; complete.')
    if args.cached_url:
        import crypto_news_trial as engine
        import instagram_ranked_news as ranked
        from economy_news_translation import load_translation_env
        load_translation_env(Path.home()/'sub/.env')
        ranked.configure_engine('crypto')
        intake.configure_admin_source(engine, args.cached_url)
        material = intake.read_manual_source(engine, dict(id='layout-check', source_url=args.cached_url,
            title_original='', source_name=''), time.time(), relaxed=True)
        source = material['title_original']+'\n'+material['source_text']+'\n'+material['article_date']
        prefix = 'coindesk-rss-v1-json\n' if material.get('source_scope') == 'coindesk_rss_summary' else 'economy-v2-json\n'
        key = hashlib.sha256((prefix+os.getenv('DEEPSEEK_MODEL','deepseek-flash')+'\n'+source).encode()).hexdigest()
        db = Path.home()/'.local/state/kiani-instagram-manual-news/assessment.sqlite3'
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as con:
            cached = con.execute('SELECT title_fa,summary_fa FROM economy_translation_cache WHERE input_hash=?',(key,)).fetchone()
        if not cached:
            raise RuntimeError('No matching saved translation; no model call was made.')
        material['assessment'] = {'story_type':'forecast'}
        print('Saved article translation:', check(material, cached[0], cached[1], output), 'slides; 64px; complete.')
print('No DeepSeek, Telegram or Instagram request was made.')

