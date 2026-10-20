"""Deterministic Persian calendar cards using the approved Kiani visual style."""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from economic_calendar_data import TEHRAN

INK, GREEN, MUTED, BG = '#173D32', '#208C68', '#708078', '#EDF4EF'
DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
MONTH_FA = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
DAY_FA = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')
DAY_EN = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
MONTH_EN = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def labels(moment, asset_root):
    libs = Path(asset_root) / 'instagram_calendar_libs'
    if libs.is_dir() and str(libs) not in sys.path:
        sys.path.insert(0, str(libs))
    import jdatetime
    local = moment.astimezone(TEHRAN)
    jalali = jdatetime.date.fromgregorian(date=local.date())
    fa = f'{DAY_FA[local.weekday()]} · {jalali.day} {MONTH_FA[jalali.month - 1]} {jalali.year}'
    en = f'{DAY_EN[local.weekday()]} · {local.day} {MONTH_EN[local.month - 1]} {local.year}'
    return fa.translate(DIGITS), en, local.strftime('%H:%M').translate(DIGITS)


def render(snapshot, output, asset_root, *, preview=False):
    output, asset_root = Path(output), Path(asset_root)
    output.mkdir(parents=True, exist_ok=True)
    fonts = {}

    def font(size, bold=False):
        key = size, bold
        if key not in fonts:
            name = 'Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf'
            fonts[key] = ImageFont.truetype(str(asset_root / 'fonts' / name), size,
                                           layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]

    def shaped(text):
        return get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')

    def fa(draw, text, xy, size, bold=False, fill=INK, anchor='rm', width=None):
        value = shaped(text)
        if width:
            while size > 18 and draw.textlength(value, font=font(size, bold)) > width:
                size -= 1
            if draw.textlength(value, font=font(size, bold)) > width:
                raise ValueError('Calendar text exceeds its reviewed layout.')
        draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)

    root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (300, 310))
    pen = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, p.split(','))) for p in node.attrib['points'].split()]
        pen.polygon([(x * 300 / lw, y * 310 / lh) for x, y in points], fill=INK)
    logo = logo.resize((70, 72), Image.Resampling.LANCZOS)

    def flag(draw, country, x, y):
        # Small code-native flags avoid external image dependencies.
        w, h = 68, 44
        draw.rounded_rectangle((x, y, x + w, y + h), radius=5, fill='#FFFFFF')
        if country == 'US':
            for i in range(0, 13, 2):
                draw.rectangle((x, y + i * h / 13, x + w, y + (i + 1) * h / 13), fill='#B82938')
            draw.rectangle((x, y, x + 29, y + 25), fill='#254571')
            for a in range(5):
                for b in range(4):
                    draw.ellipse((x + 3 + a * 5, y + 3 + b * 5, x + 5 + a * 5, y + 5 + b * 5), fill='white')
        elif country == 'EU':
            draw.rounded_rectangle((x, y, x + w, y + h), radius=5, fill='#073C99')
            for i in range(12):
                a = math.pi * i / 6
                cx, cy = x + w / 2 + math.sin(a) * 14, y + h / 2 - math.cos(a) * 14
                draw.ellipse((cx - 1.7, cy - 1.7, cx + 1.7, cy + 1.7), fill='#FFDC42')
        else:
            draw.rectangle((x, y, x + w, y + h), fill='#203D74')
            draw.line((x, y, x + w, y + h), fill='white', width=9)
            draw.line((x + w, y, x, y + h), fill='white', width=9)
            draw.line((x, y + h / 2, x + w, y + h / 2), fill='white', width=15)
            draw.line((x + w / 2, y, x + w / 2, y + h), fill='white', width=15)
            draw.line((x, y + h / 2, x + w, y + h / 2), fill='#C93540', width=8)
            draw.line((x + w / 2, y, x + w / 2, y + h), fill='#C93540', width=8)

    start, end = (datetime.fromisoformat(snapshot[k]).astimezone(TEHRAN)
                  for k in ('window_start', 'window_end'))
    last_day = end - timedelta(microseconds=1)
    date_range = f'{start.day} {MONTH_EN[start.month - 1]} – {last_day.day} {MONTH_EN[last_day.month - 1]} {last_day.year}'
    events = snapshot['events']
    pages = (len(events) + 2) // 3
    paths = []
    prefix = 'kiani-economic-calendar-' + start.strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8]
    for page in range(pages):
        image = Image.new('RGB', (1080, 1350), BG)
        draw = ImageDraw.Draw(image)
        image.paste(logo, (946, 44), logo)
        fa(draw, 'صرافی کیانی', (925, 75), 34, True)
        draw.text((925, 113), 'kiani.exchange', font=font(24), fill=MUTED, anchor='rm')
        if preview:
            draw.rounded_rectangle((64, 55, 267, 110), 26, fill='#A87322')
            fa(draw, 'پیش‌نمایش', (165, 82), 27, True, '#FFFFFF', 'mm')
        else:
            fa(draw, 'تقویم هفتگی', (64, 80), 26, True, GREEN, 'lm')
        fa(draw, 'تقویم اقتصادی پیش رو', (540, 202), 59, True, anchor='mm', width=952)
        fa(draw, f'{len(events)} رویداد منتخب در ۷ روز آینده', (540, 265), 32, anchor='mm')
        draw.rounded_rectangle((220, 301, 860, 354), 26, fill='#DDECE4')
        fa(draw, 'همه ساعت‌ها به وقت تهران', (835, 328), 27, width=415)
        draw.text((250, 328), 'UTC+3:30', font=font(25), fill=INK, anchor='lm')
        draw.text((540, 382), date_range, font=font(22), fill=MUTED, anchor='mm')
        for index, row in enumerate(events[page * 3:page * 3 + 3]):
            y = 417 + 244 * index
            draw.rounded_rectangle((64, y + 5, 1016, y + 233), 29, fill='#E1EAE4')
            draw.rounded_rectangle((64, y, 1016, y + 228), 29, fill='white')
            draw.line((335, y + 29, 335, y + 195), fill='#E3EAE6', width=2)
            flag(draw, row['flag'], 925, y + 28)
            persian, english, clock = labels(datetime.fromisoformat(row['tehran']), asset_root)
            fa(draw, persian, (900, y + 35), 23, fill=MUTED, width=530)
            draw.text((900, y + 68), english, font=font(22), fill=MUTED, anchor='rm')
            fa(draw, row['title_fa'], (990, y + 117), 37, True, width=625)
            fa(draw, row['label_fa'], (990, y + 160), 25, fill=MUTED, width=625)
            fa(draw, 'زیر نظر: ' + row['watch_fa'], (990, y + 202), 23, fill=GREEN, width=625)
            fa(draw, clock, (200, y + 100), 65, True, anchor='mm', width=250)
            fa(draw, 'تهران', (200, y + 156), 28, anchor='mm', fill=MUTED)
        draw.rounded_rectangle((302, 1180, 778, 1236), 28, fill=GREEN)
        fa(draw, 'این تقویم را ذخیره کنید', (540, 1208), 28, True, '#FFFFFF', 'mm')
        fa(draw, 'زمان‌بندی ممکن است تغییر کند.', (1016, 1270), 22, fill=MUTED)
        sources = sorted({url_name(x['source_url']) for x in events})
        draw.text((64, 1270), 'Sources: ' + ' · '.join(sources), font=font(20), fill=MUTED, anchor='lm')
        draw.text((540, 1313), 'kiani.exchange', font=font(23, True), fill=GREEN, anchor='mm')
        if pages > 1:
            draw.text((1016, 1313), f'{page + 1} / {pages}', font=font(22), fill=MUTED, anchor='rm')
        path = output / f'{prefix}-{page + 1:02}.jpg'
        image.save(path, 'JPEG', quality=95, subsampling=0)
        path.chmod(0o644)
        paths.append(str(path.resolve()))
    return paths


def url_name(url):
    return next((name for token, name in [('bls.gov', 'BLS'), ('bea.gov', 'BEA'),
                                          ('ecb.europa.eu', 'ECB'), ('bankofengland.co.uk', 'BoE'),
                                          ('federalreserve.gov', 'Fed')] if token in url), 'Official')


def caption(snapshot, asset_root):
    paragraphs = ['صرافی کیانی | تقویم اقتصادی ۷ روز آینده', 'همه ساعت‌ها به وقت تهران (UTC+3:30)']
    start, end = (datetime.fromisoformat(snapshot[k]) for k in ('window_start', 'window_end'))
    paragraphs.append('بازه: ' + labels(start, asset_root)[0] + ' تا ' + labels(end - timedelta(microseconds=1), asset_root)[0])
    for row in snapshot['events']:
        fa, en, clock = labels(datetime.fromisoformat(row['tehran']), asset_root)
        paragraphs.append(f"{row['title_fa']}\n{fa}\n{en}\nساعت {clock} تهران\nمنبع: {row['source_url']}")
    paragraphs.append('این فهرست شامل رویدادهای منتخب است. زمان‌بندی ممکن است تغییر کند؛ پیش از رویداد، تقویم رسمی را بررسی کنید.')
    paragraphs.append('kiani.exchange')
    return '\n\n'.join(paragraphs)
