"""Code-native Persian news cards using the existing Instagram font and logo."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageOps

INK, MUTED, GREEN, RED = '#15201B', '#708078', '#1C8C67', '#D9362C'
DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'meta':
            values = dict(attrs)
            key = values.get('property') or values.get('name')
            if key and values.get('content'):
                self.values[key.lower()] = values['content']


def metadata(story):
    if story.get('image_url') and story.get('article_date'):
        return story
    try:
        request = Request(story['source_url'], headers={'User-Agent': 'KianiExchange-InstagramNews/1.0'})
        with urlopen(request, timeout=15) as response:
            html = response.read(2_000_001)
        if len(html) > 2_000_000:
            raise ValueError('Article metadata is too large')
        parser = Metadata()
        parser.feed(html.decode('utf-8', errors='replace'))
        values = parser.values
        story = dict(story)
        image = values.get('og:image') or values.get('twitter:image')
        story['image_url'] = story.get('image_url') or (urljoin(story['source_url'], image) if image else None)
        story['source_name'] = values.get('og:site_name') or story['source_name']
        story['article_date'] = story.get('article_date') or values.get('article:published_time', '')[:10] or None
    except Exception as exc:
        print(f'Article metadata unavailable ({type(exc).__name__}); using saved story text.')
    return story


def hero_image(story, cache):
    url = story.get('image_url')
    if not url:
        return None
    if urlsplit(url).scheme not in {'http', 'https'}:
        return None
    cache.mkdir(parents=True, exist_ok=True)
    saved = cache / (hashlib.sha256(url.encode()).hexdigest() + '.jpg')
    try:
        if saved.is_file():
            with Image.open(saved) as image:
                return image.convert('RGB')
        request = Request(url, headers={'User-Agent': 'KianiExchange-InstagramNews/1.0'})
        with urlopen(request, timeout=20) as response:
            if not response.headers.get_content_type().startswith('image/'):
                raise ValueError('Not a source image')
            data = response.read(10_000_001)
        if len(data) > 10_000_000:
            raise ValueError('Source image is too large')
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert('RGB')
            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            image.save(saved, quality=95)
            return image.copy()
    except Exception as exc:
        print(f'Source illustration unavailable ({type(exc).__name__}); rendering a branded text card.')
        return None


def render_news(stories, output, asset_root, *, news_label='خبر کریپتو',
                caption_title='صرافی کیانی | خبر کریپتو',
                caption_footer='اخبار فارسی کریپتو در تلگرام: https://t.me/kriptofarsi',
                require_image=False):
    output = Path(output).expanduser().resolve()
    asset_root = Path(asset_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    fonts = {}

    def font(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            path = asset_root / 'fonts' / ('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')
            fonts[key] = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]

    def rtl(text):
        return get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')

    def fa(draw, text, xy, size, *, bold=False, fill=INK, anchor='rm'):
        draw.text(xy, rtl(text), font=font(size, bold), fill=fill, anchor=anchor)

    def wrap(draw, text, size, bold=False, width=952):
        rows, row = [], ''
        for word in str(text).split():
            candidate = (row + ' ' + word).strip()
            if row and draw.textlength(rtl(candidate), font=font(size, bold)) > width:
                rows.append(row)
                row = word
            else:
                row = candidate
        if row:
            rows.append(row)
        for row in rows:
            if draw.textlength(rtl(row), font=font(size, bold)) > width:
                raise ValueError('A news word/link is too wide; edit the saved Persian summary before publishing.')
        return rows

    logo_root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, logo_root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (256, 256))
    ld = ImageDraw.Draw(logo)
    for node in logo_root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        ld.polygon([(x * 256/lw, y * 256/lh) for x, y in points], fill=INK)
    logo = logo.resize((72, 74), Image.Resampling.LANCZOS)

    def base(story, page, pages):
        image = Image.new('RGB', (1080, 1350), '#FFFFFF')
        draw = ImageDraw.Draw(image)
        image.paste(logo, (944, 50), logo)
        fa(draw, 'صرافی کیانی', (925, 73), 34, bold=True)
        draw.text((925, 111), 'kiani.exchange', font=font(25), fill=MUTED, anchor='rm')
        draw.rounded_rectangle((64, 61, 257, 120), radius=28, fill='#FDEDEB')
        fa(draw, news_label, (160, 92), 27, bold=True, fill=RED, anchor='mm')
        draw.line((64, 1246, 1016, 1246), fill='#E4EAE6', width=2)
        draw.text((64, 1282), 'kiani.exchange', font=font(25, True), fill=GREEN, anchor='lm')
        label = f"Source: {story['source_name']}"
        if story.get('article_date'):
            label += ' · ' + story['article_date']
        size = 24
        while draw.textlength(label, font=font(size)) > 720 and size > 16:
            size -= 1
        draw.text((1016, 1282), label, font=font(size), fill=MUTED, anchor='rm')
        if pages > 1:
            draw.text((64, 1222), f'{page}/{pages}', font=font(20), fill=MUTED, anchor='lm')
        return image, draw

    frames, enriched = [], []
    for saved in stories:
        story = metadata(dict(saved))
        enriched.append(story)
        hero = hero_image(story, output / '.source-images')
        if require_image and hero is None:
            raise ValueError('A source illustration is required for this news post.')
        scratch = ImageDraw.Draw(Image.new('RGB', (1080, 1350)))
        title_size = 61
        title_rows = wrap(scratch, story['title_fa'], title_size, True)
        while len(title_rows) > 3 and title_size > 42:
            title_size -= 1
            title_rows = wrap(scratch, story['title_fa'], title_size, True)
        if len(title_rows) > 3:
            raise ValueError('News headline is too long for the card; shorten the saved title before publishing.')
        title_bottom = 165 + len(title_rows) * (title_size + 19)
        hero_top = title_bottom + 24
        hero_height = min(488, max(310, 810 - hero_top)) if hero else 0
        body_top = hero_top + hero_height + 31
        highlights = json.loads(story.get('highlights_json', '[]'))[:3]
        if highlights and len(highlights) == 3:
            body_top += 160
        body_size = 30
        body_rows = wrap(scratch, story['summary_fa'], body_size)
        available = 1205 - body_top
        while len(body_rows) * (body_size + 13) > available and body_size > 25:
            body_size -= 1
            body_rows = wrap(scratch, story['summary_fa'], body_size)
        capacity = max(1, int(available // (body_size + 13)))
        first_rows, remaining = body_rows[:capacity], body_rows[capacity:]
        # Longer summaries continue on readable text slides; never silently truncate.
        continuation = []
        if remaining:
            # Rewrap the actual remaining words, rather than the already shaped display text.
            tail = ' '.join(remaining)
            continuation_rows = wrap(scratch, tail, 35)
            continuation_capacity = max(1, int((1205-title_bottom-55)//50))
            continuation = [continuation_rows[i:i+continuation_capacity]
                            for i in range(0, len(continuation_rows), continuation_capacity)]
        pages = 1 + len(continuation)
        image, draw = base(story, 1, pages)
        for index, row in enumerate(title_rows):
            fa(draw, row, (1016, 172 + index * (title_size + 19)), title_size, bold=True, anchor='rt')
        if hero:
            box = Image.new('RGB', (952, hero_height), '#F0F3F1')
            illustration = ImageOps.contain(hero, box.size, Image.Resampling.LANCZOS)
            box.paste(illustration, ((952-illustration.width)//2, (hero_height-illustration.height)//2))
            mask = Image.new('L', box.size)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 951, hero_height-1), radius=27, fill=255)
            image.paste(box, (64, hero_top), mask)
        if len(highlights) == 3:
            top = hero_top + hero_height + 31
            for index, item in enumerate(reversed(highlights)):
                x = 64 + index * 324
                draw.rounded_rectangle((x, top, x+304, top+135), radius=22, fill='#FFFFFF', outline='#E3EAE6', width=2)
                fa(draw, str(item['value']), (x+152, top+48), 51, bold=True,
                   fill=RED if index == 2 else INK, anchor='mm')
                fa(draw, str(item['label']), (x+152, top+103), 25, fill=MUTED, anchor='mm')
        for index, row in enumerate(first_rows):
            fa(draw, row, (1016, body_top+index*(body_size+13)), body_size, anchor='rt')
        frames.append(image)
        for page, rows in enumerate(continuation, 2):
            image, draw = base(story, page, pages)
            for index, row in enumerate(title_rows):
                fa(draw, row, (1016, 172+index*(title_size+19)), title_size, bold=True, anchor='rt')
            for index, row in enumerate(rows):
                fa(draw, row, (1016, title_bottom+55+index*50), 35, anchor='rt')
            frames.append(image)

    if len(frames) > 10:
        raise ValueError('News summaries require more than ten slides; select fewer stories.')
    prefix = 'kiani-news-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    paths = []
    for index, image in enumerate(frames, 1):
        path = output / f'{prefix}-{index:02}.jpg'
        image.save(path, quality=95, subsampling=0)
        paths.append(path)
    paragraphs = [caption_title]
    for story in enriched:
        paragraphs.append(story['title_fa'])
        paragraphs.append(story['summary_fa'])
        paragraphs.append('منبع: ' + story['source_name'] + '\n' + story['source_url'])
    if caption_footer:
        paragraphs.append(caption_footer)
    caption = '\n\n'.join(paragraphs)
    if len(caption) > 2200:
        paragraphs = [caption_title]
        paragraphs.extend(story['title_fa'] + '\nمنبع: ' + story['source_name'] + '\n' + story['source_url'] for story in enriched)
        paragraphs.append('متن کامل خبرها روی اسلایدها')
        if caption_footer:
            paragraphs.append(caption_footer)
        caption = '\n\n'.join(paragraphs)
    if len(caption) > 2200:
        raise ValueError('News caption exceeds the Instagram limit; select fewer stories.')
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'slides': [path.name for path in paths],
                'caption': caption, 'stories': enriched}
    (output / (prefix + '.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return paths, caption, manifest
