#!/usr/bin/env python3
"""Verify crypto/economy image layouts using previously published stories."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--runtime',required=True,type=Path)
args=p.parse_args()
runtime=args.runtime.resolve()
sys.path[:0]=[str(runtime),str(runtime/'selector_trial_runtime')]
import crypto_news_trial as engine
import instagram_ranked_news as ranked
import instagram_news_renderer as renderer
from instagram_news_slide_images import collect, caption_credit, image_key

home=Path.home()
assets=home/'kiani-instagram-publisher'
renderer.metadata=lambda story: story
for kind, db in (
    ('crypto',home/'.local/state/kiani-instagram-news/news.sqlite3'),
    ('economy',home/'.local/state/kiani-instagram-economy/economy.sqlite3'),
):
    if not db.is_file() or db.is_symlink():
        raise RuntimeError('Existing '+kind+' news history is unavailable.')
    ranked.configure_engine(kind)
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute('''SELECT n.source_url,n.source_name,n.image_url,n.title_original,
                n.title_fa,n.summary_fa,n.article_date
            FROM instagram_news n JOIN instagram_news_publications p ON p.story_id=n.id
            WHERE p.status='published' ORDER BY p.finished_at DESC LIMIT 5''').fetchall()
    if not rows: raise RuntimeError('No completed '+kind+' news history is available.')
    success=False
    for row in rows:
        story=dict(row)
        if not all(isinstance(story.get(k),str) and story[k].strip()
                   for k in ('source_url','source_name','title_original','title_fa','summary_fa')):
            continue
        print(kind+': checking a previously published article for distinct images.',flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix='kiani-auto-news-images-') as tmp:
                folder=Path(tmp)
                images=collect(engine,story,folder,origin='automatic',minimum=2)
                if image_key(images[0]['path'])==image_key(images[1]['path']):
                    raise RuntimeError('First and second images are identical.')
                paths,caption,manifest=renderer.render_news([story],folder/'rendered',assets,
                    slide_images=[item['path'] for item in images],minimum_slide_images=2,adaptive_body=True)
                used=images[:manifest['used_slide_images']]
                credit=caption_credit(used)
                if len(caption)+len(credit)+2>2200 or not manifest['text_complete'] or manifest['body_font_px']!=64:
                    raise RuntimeError('Readable content or image attribution cannot be preserved.')
                if manifest['illustrated_body_pages']<1 or len(paths)<2:
                    raise RuntimeError('The first two images did not reach their slides.')
                print(kind+': verified',len(images),'distinct images;',len(paths),
                      'slides;',manifest['illustrated_body_pages'],'illustrated body slides.',flush=True)
                success=True
                break
        except Exception as exc:
            print(kind+': example unavailable:',type(exc).__name__,flush=True)
    if not success:
        raise RuntimeError('No recent '+kind+' example had two verified images; nothing installed.')
print('Automatic crypto and economy previews passed. No DeepSeek or Instagram request was made.',flush=True)

