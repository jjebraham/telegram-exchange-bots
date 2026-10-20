"""Persian crypto calendar cards, preserving date precision and network labels."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from crypto_calendar_data import TEHRAN
from instagram_economic_calendar_renderer import labels, DIGITS, INK, GREEN, MUTED, BG

AMBER = '#A87322'


def event_labels(row, asset_root):
    if row['precision'] == 'date':
        # Noon is only an internal civil-date conversion anchor, never an event time.
        anchor = datetime.combine(date.fromisoformat(row['tehran_date']), time(12), TEHRAN)
        fa, en, _ = labels(anchor, asset_root)
        return 'حدود ' + fa, 'Around ' + en, None
    fa, en, clock = labels(datetime.fromisoformat(row['tehran']), asset_root)
    return fa, en, clock


def render(snapshot, output, asset_root, *, preview=False):
    output, asset_root = Path(output), Path(asset_root)
    output.mkdir(parents=True, exist_ok=True)
    fonts = {}

    def font(size, bold=False):
        key = size, bold
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(asset_root / 'fonts' / ('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')),
                                           size, layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]

    def fa(draw, text, xy, size, bold=False, fill=INK, anchor='rm', width=None):
        value = get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')
        if width:
            while size > 18 and draw.textlength(value, font=font(size, bold)) > width:
                size -= 1
            if draw.textlength(value, font=font(size, bold)) > width:
                raise ValueError('Crypto calendar text exceeds the reviewed layout.')
        draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)

    root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (300, 310))
    pen = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        pen.polygon([(x * 300 / lw, y * 310 / lh) for x, y in points], fill=INK)
    logo = logo.resize((70, 72), Image.Resampling.LANCZOS)
    start, end = (datetime.fromisoformat(snapshot[k]) for k in ('window_start', 'window_end'))
    last = end - timedelta(microseconds=1)
    date_range = start.strftime('%d %b %Y, %H:%M') + ' – ' + end.strftime('%d %b %Y, %H:%M')
    start_fa = labels(start, asset_root)[0].split(' · ')[-1]
    end_fa = labels(last, asset_root)[0].split(' · ')[-1]
    events = snapshot['events']
    pages, paths = (len(events) + 2) // 3, []
    # Balance four events as 2+2 rather than leaving a mostly empty second slide.
    sizes = [len(events) // pages + (index < len(events) % pages) for index in range(pages)]
    prefix = 'kiani-crypto-calendar-' + start.strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8]
    for page in range(pages):
        image = Image.new('RGB', (1080, 1350), BG)
        draw = ImageDraw.Draw(image)
        image.paste(logo, (946, 44), logo)
        fa(draw, 'صرافی کیانی', (925, 75), 34, True)
        draw.text((925, 113), 'kiani.exchange', font=font(24), fill=MUTED, anchor='rm')
        if preview:
            draw.rounded_rectangle((64, 55, 267, 110), 26, fill=AMBER)
            fa(draw, 'پیش‌نمایش', (165, 82), 27, True, 'white', 'mm')
        else:
            fa(draw, 'تقویم هفتگی', (64, 80), 26, True, GREEN, 'lm')
        fa(draw, 'تقویم هفتگی کریپتو', (540, 203), 62, True, anchor='mm', width=952)
        fa(draw, f'{len(events)} رویداد منتخب در ۷ روز آینده', (540, 264), 32, anchor='mm')
        draw.rounded_rectangle((220, 298, 860, 349), 25, fill='#DDECE4')
        fa(draw, 'ساعت‌های اعلام‌شده به وقت تهران', (835, 324), 25, width=420)
        draw.text((245, 324), 'UTC+3:30', font=font(24), fill=INK, anchor='lm')
        fa(draw, start_fa + ' تا ' + end_fa, (540, 377), 23, anchor='mm', width=952)
        draw.text((540, 409), date_range, font=font(19), fill=MUTED, anchor='mm')
        offset, count = sum(sizes[:page]), sizes[page]
        height = {1: 440, 2: 330, 3: 221}[count]
        for index, row in enumerate(events[offset:offset + count]):
            y = 443 + (height + 16) * index + (100 if count == 1 else 0)
            scale = lambda value: value * height / 221
            draw.rounded_rectangle((64, y + 5, 1016, y + height + 5), 27, fill='#E1EAE4')
            draw.rounded_rectangle((64, y, 1016, y + height), 27, fill='white')
            draw.line((335, y + scale(25), 335, y + scale(192)), fill='#E3EAE6', width=2)
            persian, english, clock = event_labels(row, asset_root)
            fa(draw, persian, (990, y + scale(27)), 24, fill=MUTED, width=625)
            draw.text((990, y + scale(55)), english, font=font(22), fill=MUTED, anchor='rm')
            fa(draw, row['title_fa'], (990, y + scale(96)), 36, True, width=625)
            fa(draw, row['label_fa'], (990, y + scale(133)), 27, True, width=625)
            color = AMBER if row['status'] == 'estimated' else GREEN
            draw.rounded_rectangle((361, y + scale(152), 994, y + scale(181)), 14, fill='#FFF2DD' if row['status'] == 'estimated' else '#E6F3EB')
            fa(draw, row['status_fa'], (977, y + scale(166)), 22, True, color, width=598)
            fa(draw, 'زیر نظر: ' + row['watch_fa'], (990, y + scale(203)), 22, fill=MUTED, width=625)
            if clock:
                fa(draw, clock, (200, y + scale(95)), 66, True, anchor='mm', width=250)
                fa(draw, 'تهران', (200, y + scale(151)), 28, anchor='mm', fill=MUTED)
            else:
                fa(draw, 'ساعت', (200, y + scale(82)), 32, True, anchor='mm', fill=color)
                fa(draw, 'اعلام نشده', (200, y + scale(128)), 30, True, anchor='mm', fill=color, width=240)
                fa(draw, 'تاریخ تخمینی', (200, y + scale(171)), 23, anchor='mm', fill=MUTED)
        draw.rounded_rectangle((302, 1180, 778, 1236), 28, fill=GREEN)
        fa(draw, 'این تقویم را ذخیره کنید', (540, 1208), 28, True, 'white', 'mm')
        fa(draw, 'رویدادهای منتخب؛ تاریخ تخمینی ممکن است تغییر کند.', (540, 1270), 22, fill=MUTED, anchor='mm', width=952)
        source_names = sorted({row['family'] for row in events})
        draw.text((64, 1313), ' · '.join(source_names), font=font(19), fill=MUTED, anchor='lm')
        draw.text((1016, 1313), f'kiani.exchange   {page + 1}/{pages}', font=font(22), fill=GREEN, anchor='rm')
        path = output / f'{prefix}-{page + 1:02}.jpg'
        image.save(path, 'JPEG', quality=95, subsampling=0)
        path.chmod(0o644)
        paths.append(str(path.resolve()))
    return paths


def caption(snapshot, asset_root):
    lines = ['صرافی کیانی | تقویم هفتگی کریپتو', 'ساعت‌های اعلام‌شده به وقت تهران (UTC+3:30)']
    for row in snapshot['events']:
        fa, en, clock = event_labels(row, asset_root)
        timing = 'ساعت ' + clock + ' تهران' if clock else 'ساعت اعلام نشده؛ تاریخ برآوردی از برنامه واگذاری'
        lines.append(f"{row['title_fa']}\n{row['label_fa']}\n{fa}\n{en}\n{timing}\n{row['source_url']}")
    lines.append('این فهرست منتخب است. شبکه آزمایشی با شبکه اصلی متفاوت است؛ تاریخ‌های تخمینی ممکن است تغییر کنند. آزادسازی توکن به معنی فروش قطعی نیست.')
    lines.append('kiani.exchange')
    return '\n\n'.join(lines)
