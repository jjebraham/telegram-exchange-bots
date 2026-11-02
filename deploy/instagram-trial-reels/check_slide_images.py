#!/usr/bin/env python3
"""Offline verification of first/second news slide images and text."""
import argparse
from pathlib import Path
import sys
import tempfile
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True, type=Path)
p.add_argument('--assets', type=Path, default=Path.home()/'kiani-instagram-publisher')
args = p.parse_args()
root = args.runtime.resolve()
sys.path[:0] = [str(root), str(root/'selector_trial_runtime')]
import instagram_news_renderer as renderer

story = dict(title_fa='نمونه خبر درباره تغییرات بازار',
             summary_fa=' '.join(['این یک متن آزمایشی برای بررسی تصویر و خوانایی خبر در هر اسلاید است.']*10),
             source_url='https://example.com/news', source_name='Example', article_date='', image_url=None)
renderer.metadata = lambda value: value
renderer.hero_image = lambda story, cache: None
with tempfile.TemporaryDirectory(prefix='kiani-slide-layout-') as tmp:
    directory = Path(tmp)
    pictures = []
    for i, color in enumerate(('red','blue','green','purple')):
        path = directory/(str(i)+'.jpg')
        Image.new('RGB',(900,500),color).save(path)
        pictures.append(path)
    paths, caption, manifest = renderer.render_news(
        [story], directory/'out', args.assets, adaptive_body=True,
        slide_images=pictures, minimum_slide_images=2)
    assert manifest['text_complete'] and manifest['body_font_px'] == 64
    assert manifest['summary_normalized'] == story['summary_fa']
    assert manifest['illustrated_body_pages'] >= 1
    with Image.open(paths[0]) as cover, Image.open(paths[1]) as second:
        first_pixel = cover.getpixel((150,300))
        second_pixel = second.getpixel((150,500))
    assert first_pixel[0] > 180 and first_pixel[2] < 70
    assert second_pixel[2] > 180 and second_pixel[0] < 70
    try:
        renderer.render_news([story], directory/'missing', args.assets,
                             slide_images=pictures[:1], minimum_slide_images=2)
    except ValueError:
        pass
    else:
        raise RuntimeError('Carousel did not reject a missing required image.')
    print('Cover and second slide have distinct pictures; complete text preserved at 64px.')
    print('Illustrated body slides:', manifest['illustrated_body_pages'], '| total slides:', len(paths))
print('No network, DeepSeek, Telegram or Instagram request was made.')

