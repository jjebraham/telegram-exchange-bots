"""Readable Option B news carousels with the existing Kiani font and logo."""
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
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

INK, MUTED, GREEN, RED = '#173D32', '#70857D', '#1C8C67', '#D9362C'
LAYOUT_VERSION = 'kiani-news-carousel-b-v1'
BODY_FONT_PX = 64
BODY_LEADING = 96
BODY_LINES_PER_PAGE = 7
ASSET_FILES = ('assets/instagram/kiani-logo.svg', 'fonts/Vazirmatn-Regular.ttf', 'fonts/Vazirmatn-Bold.ttf')
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
    """Render one cover and lossless large-type summary pages; never publish."""
    if len(stories) != 1:
        raise ValueError('Each readable news carousel must contain exactly one story.')
    output = Path(output).expanduser().resolve()
    asset_root = Path(asset_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    story = metadata(dict(stories[0]))
    title = re.sub(r'\s+', ' ', str(story.get('title_fa') or '')).strip()
    summary = re.sub(r'\s+', ' ', str(story.get('summary_fa') or '')).strip()
    if not title or not summary or len(title) > 300 or len(summary) > 8000:
        raise ValueError('A bounded, nonempty verified headline and summary are required.')
    fonts = {}

    def font(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            path = asset_root / 'fonts' / ('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')
            fonts[key] = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]

    def rtl(text):
        return get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')

    def fa(draw, text, xy, size, *, bold=False, fill=INK, anchor='rt'):
        draw.text(xy, rtl(text), font=font(size, bold), fill=fill, anchor=anchor)

    scratch = ImageDraw.Draw(Image.new('RGB', (1080, 1350)))

    def wrap_spans(text, size, width, bold=False):
        """Keep original character spans, including when a long token must wrap."""
        rows, cursor = [], 0
        while cursor < len(text):
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor == len(text):
                break
            end = cursor
            while end < len(text) and scratch.textlength(rtl(text[cursor:end+1]), font=font(size, bold)) <= width:
                end += 1
            if end == cursor:
                raise ValueError('A glyph exceeds the fixed readable text width.')
            if end < len(text):
                boundary = text.rfind(' ', cursor, end+1)
                if boundary > cursor:
                    end = boundary
            piece = text[cursor:end].rstrip()
            rows.append(dict(start=cursor, end=cursor+len(piece), text=piece))
            cursor = end
        return rows

    # Give each complete sentence its own line boundary so a few words from
    # the next sentence cannot become a dangling tail at the page bottom.
    lines, start = [], 0
    stops = [(match.end(1), match.end()) for match in re.finditer(r'([.!?؟][»”"]?)(\s+)', summary)]
    for end, following in stops + [(len(summary), len(summary))]:
        for row in wrap_spans(summary[start:end], BODY_FONT_PX, 824):
            lines.append(dict(start=row['start']+start, end=row['end']+start, text=row['text']))
        start = following
    pages = []
    while lines:
        count = min(BODY_LINES_PER_PAGE, len(lines))
        if len(lines) > count:
            for candidate in range(count, max(2, count-4), -1):
                if re.search(r'[.!?؟][»”"]?$', lines[candidate-1]['text']):
                    count = candidate
                    break
        pages.append(lines[:count])
        lines = lines[count:]
    if not pages or len(pages) > 9:
        raise ValueError('The full summary exceeds ten large-type slides; no text was truncated.')
    page_spans = [dict(start=rows[0]['start'], end=rows[-1]['end'],
                       text=summary[rows[0]['start']:rows[-1]['end']],
                       lines=rows) for rows in pages]
    cursor, reconstructed = 0, []
    for page in page_spans:
        if summary[cursor:page['start']].strip():
            raise ValueError('Pagination omitted source text.')
        page['separator_before'] = summary[cursor:page['start']]
        reconstructed.append(page['separator_before'] + page['text'])
        cursor = page['end']
    if ''.join(reconstructed) != summary or cursor != len(summary):
        raise ValueError('Summary text changed during pagination.')

    headline_rows, headline_size = None, None
    for size in (88, 84, 80, 76, 72):
        candidate = wrap_spans(title, size, 864, True)
        if len(candidate) <= 6 and len(candidate)*(size+18)+80 <= 620:
            headline_rows, headline_size = candidate, size
            break
    if headline_rows is None:
        raise ValueError('The complete headline needs editorial shortening; readable fonts were not reduced.')

    hero = hero_image(story, output / '.source-images')
    if require_image and hero is None:
        raise ValueError('A source illustration is required for this news post.')
    logo_root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, logo_root.attrib['viewBox'].split())
    mark = Image.new('RGBA', (248, 248))
    ld = ImageDraw.Draw(mark)
    for node in logo_root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        ld.polygon([(x*248/lw, y*248/lh) for x, y in points], fill=INK)
    mark = mark.resize((62, 62), Image.Resampling.LANCZOS)
    total = len(pages)+1

    def arrow(draw, y, *, white=False):
        fill = '#FFFFFF' if white else GREEN
        draw.line((148, y, 102, y), fill=fill, width=5)
        draw.line((116, y-14, 102, y, 116, y+14), fill=fill, width=5)

    def base(page):
        image = Image.new('RGB', (1080, 1350), '#EDF4EF')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((64, 55, 1016, 66), radius=5, fill='#D8E6DE')
        draw.rounded_rectangle((1016-round(952*page/total), 55, 1016, 66), radius=5, fill=GREEN)
        image.paste(mark, (954, 108), mark)
        fa(draw, 'صرافی کیانی', (934, 111), 34, bold=True)
        draw.text((934, 159), 'kiani.exchange', font=font(25), fill=MUTED, anchor='rt')
        draw.rounded_rectangle((64, 111, 306, 165), radius=26, fill='#DDEDE4')
        fa(draw, news_label, (185, 137), 29, bold=True, fill=GREEN, anchor='mm')
        draw.line((64, 1240, 1016, 1240), fill='#D8E6DE', width=2)
        source = 'Source: ' + str(story.get('source_name') or 'Original publisher')
        source_size = 24
        while draw.textlength(source, font=font(source_size)) > 680 and source_size > 18:
            source_size -= 1
        if draw.textlength(source, font=font(source_size)) > 680:
            raise ValueError('The source label is too wide; full attribution was not truncated.')
        draw.text((64, 1270), source, font=font(source_size), fill=MUTED, anchor='lm')
        if story.get('article_date'):
            fa(draw, str(story['article_date']), (1016, 1270), 25, fill=MUTED, anchor='rm')
        draw.text((64, 1318), 'kiani.exchange', font=font(24, True), fill=GREEN, anchor='lm')
        fa(draw, f'اسلاید {page} از {total}', (1016, 1318), 25, fill=MUTED, anchor='rm')
        return image, draw

    cover, draw = base(1)
    box_size = (1016, 572)
    if hero is not None:
        backdrop = ImageOps.fit(hero, box_size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(24))
        illustration = ImageOps.contain(hero, box_size, Image.Resampling.LANCZOS)
        backdrop.paste(illustration, ((box_size[0]-illustration.width)//2, (box_size[1]-illustration.height)//2))
    else:
        backdrop = Image.new('RGB', box_size, '#DDEDE4')
        ghost = mark.resize((218, 218), Image.Resampling.LANCZOS)
        backdrop.paste(ghost, (399, 150), ghost)
    mask = Image.new('L', box_size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 1015, 571), radius=26, fill=255)
    cover.paste(backdrop, (32, 212), mask)
    panel_height = max(420, len(headline_rows)*(headline_size+18)+80)
    panel_top = 1113-panel_height
    draw.rounded_rectangle((64, panel_top, 1016, 1113), radius=32, fill='#FFFFFF')
    for index, row in enumerate(headline_rows):
        fa(draw, row['text'], (968, panel_top+40+index*(headline_size+18)), headline_size, bold=True)
    draw.rounded_rectangle((64, 1162, 1016, 1229), radius=32, fill=GREEN)
    fa(draw, 'برای خواندن خبر به چپ بکشید', (958, 1196), 35, bold=True, fill='white', anchor='rm')
    arrow(draw, 1196, white=True)
    frames = [cover]
    for index, rows in enumerate(pages, 2):
        image, draw = base(index)
        heading = 'اصل خبر' if index == 2 else 'ادامه خبر'
        fa(draw, heading, (1016, 264), 80, bold=True)
        draw.rounded_rectangle((856, 389, 1016, 397), radius=4, fill=GREEN)
        draw.rounded_rectangle((64, 425, 1016, 1145), radius=32, fill='#FFFFFF')
        block_height = (len(rows)-1)*BODY_LEADING + BODY_FONT_PX
        top = 425 + max(36, (720-block_height)//2)
        for row_index, row in enumerate(rows):
            y = top + row_index*BODY_LEADING
            shaped = rtl(row['text'])
            bounds = draw.textbbox((952, y), shaped, font=font(BODY_FONT_PX), anchor='rt')
            if bounds[0] < 112 or bounds[2] > 968 or bounds[1] < 440 or bounds[3] > 1115:
                raise ValueError('Large-type text exceeds its safe card; nothing was truncated.')
            fa(draw, row['text'], (952, y), BODY_FONT_PX)
        if index < total:
            fa(draw, 'به چپ بکشید', (1016, 1184), 35, bold=True, fill=GREEN)
            arrow(draw, 1200)
        else:
            fa(draw, 'دیدگاه شما چیست؟', (1016, 1184), 36, bold=True, fill=GREEN)
        frames.append(image)

    prefix = 'kiani-news-carousel-b-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    paths = []
    for index, image in enumerate(frames, 1):
        path = output / f'{prefix}-{index:02}.jpg'
        image.save(path, 'JPEG', quality=95, subsampling=0)
        paths.append(path)
    paragraphs = [caption_title, story['title_fa'], story['summary_fa'],
                  'منبع: ' + story['source_name'] + '\n' + story['source_url']]
    if caption_footer:
        paragraphs.append(caption_footer)
    caption = '\n\n'.join(paragraphs)
    if len(caption) > 2200:
        paragraphs = [caption_title, story['title_fa'],
                      'متن کامل خبر روی اسلایدها',
                      'منبع: ' + story['source_name'] + '\n' + story['source_url']]
        if caption_footer:
            paragraphs.append(caption_footer)
        caption = '\n\n'.join(paragraphs)
    if len(caption) > 2200:
        raise ValueError('News caption exceeds the Instagram limit.')
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(), slides=[p.name for p in paths],
                    caption=caption, stories=[story], layout_version=LAYOUT_VERSION,
                    body_font_px=BODY_FONT_PX, body_leading=BODY_LEADING,
                    max_body_lines=BODY_LINES_PER_PAGE, body_pages=page_spans,
                    summary_normalized=summary, summary_sha256=hashlib.sha256(summary.encode()).hexdigest(),
                    text_complete=True, hero_available=hero is not None, headline_font_px=headline_size,
                    assets_fingerprint=hashlib.sha256(b'\0'.join(n.encode()+b'\0'+(asset_root/n).read_bytes()
                                                               for n in ASSET_FILES)).hexdigest())
    (output / (prefix + '.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'News carousel: {len(paths)} slides; body {BODY_FONT_PX}px; full verified summary preserved.', flush=True)
    return paths, caption, manifest
